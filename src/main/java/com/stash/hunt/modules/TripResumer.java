package com.stash.hunt.modules;

import baritone.api.BaritoneAPI;
import baritone.api.IBaritone;
import baritone.api.pathing.goals.Goal;
import baritone.api.pathing.goals.GoalBlock;
import baritone.api.pathing.goals.GoalNear;
import baritone.api.pathing.goals.GoalXZ;
import com.google.gson.Gson;
import com.google.gson.GsonBuilder;
import com.stash.hunt.Addon;
import meteordevelopment.meteorclient.MeteorClient;
import meteordevelopment.meteorclient.events.game.GameJoinedEvent;
import meteordevelopment.meteorclient.events.game.GameLeftEvent;
import meteordevelopment.meteorclient.events.game.ReceiveMessageEvent;
import meteordevelopment.meteorclient.events.packets.PacketEvent;
import meteordevelopment.meteorclient.events.world.TickEvent;
import meteordevelopment.meteorclient.settings.BoolSetting;
import meteordevelopment.meteorclient.settings.IntSetting;
import meteordevelopment.meteorclient.settings.Setting;
import meteordevelopment.meteorclient.settings.SettingGroup;
import meteordevelopment.meteorclient.settings.StringSetting;
import meteordevelopment.meteorclient.systems.modules.Module;
import meteordevelopment.meteorclient.systems.modules.Modules;
import meteordevelopment.orbit.EventHandler;
import net.minecraft.network.packet.s2c.common.CustomPayloadS2CPacket;
import net.minecraft.network.packet.s2c.play.ChatMessageS2CPacket;
import net.minecraft.network.packet.s2c.play.GameMessageS2CPacket;
import net.minecraft.network.packet.s2c.play.OverlayMessageS2CPacket;
import net.minecraft.network.packet.s2c.play.ProfilelessChatMessageS2CPacket;
import net.minecraft.network.packet.s2c.play.SubtitleS2CPacket;
import net.minecraft.network.packet.s2c.play.TitleS2CPacket;
import net.minecraft.util.math.BlockPos;
import java.io.File;
import java.io.FileReader;
import java.io.FileWriter;
import java.io.IOException;
import java.io.Reader;
import java.io.Writer;
import java.util.Set;
import java.util.regex.Pattern;
import java.util.regex.PatternSyntaxException;

public class TripResumer extends Module
{
    private final SettingGroup sgGeneral = settings.getDefaultGroup();

    private final Setting<String> mainServer = sgGeneral.add(new StringSetting.Builder()
        .name("main-server-ip")
        .description("Substring that identifies the main server's IP. Leave empty to consider any IP (except backup) as main.")
        .defaultValue("")
        .build()
    );

    private final Setting<String> backupServer = sgGeneral.add(new StringSetting.Builder()
        .name("backup-server-ip")
        .description("Substring that identifies the backup server's IP. Takes priority over the main match when matched.")
        .defaultValue("")
        .build()
    );

    private final Setting<String> mainChatKeyword = sgGeneral.add(new StringSetting.Builder()
        .name("main-chat-keyword")
        .description("If a chat message contains this text you are considered back on the main server and the trip resumes (also used when require-main-keyword is on).")
        .defaultValue("")
        .build()
    );

    private final Setting<String> backupChatKeyword = sgGeneral.add(new StringSetting.Builder()
        .name("backup-chat-keyword")
        .description("If a chat message contains this text you are considered on the backup server and the trip is put on hold.")
        .defaultValue("")
        .build()
    );

    private final Setting<Boolean> requireMainKeyword = sgGeneral.add(new BoolSetting.Builder()
        .name("require-main-keyword")
        .description("Never auto-resume from the IP alone; wait until a message containing main-chat-keyword arrives. Use this when the backup shares the same IP.")
        .defaultValue(false)
        .build()
    );

    private final Setting<Boolean> resumeOnUnknown = sgGeneral.add(new BoolSetting.Builder()
        .name("resume-on-unknown")
        .description("Resume the trip when connected to a server that matches neither the main nor the backup IP.")
        .defaultValue(false)
        .build()
    );

    private final Setting<Integer> resumeDelay = sgGeneral.add(new IntSetting.Builder()
        .name("resume-delay")
        .description("Ticks to wait after the main server is confirmed before resuming the trip.")
        .defaultValue(100)
        .min(0)
        .sliderMax(600)
        .build()
    );

    private final Setting<Boolean> debugLog = sgGeneral.add(new BoolSetting.Builder()
        .name("debug-log")
        .description("Log every chat text that arrives (via packets and events) to the game log so you can verify what the module actually receives.")
        .defaultValue(false)
        .build()
    );

    private enum State { IDLE, ARMED, PENDING_RESUME }

    private static final Gson GSON = new GsonBuilder().setPrettyPrinting().create();

    private static final Set<Class<?>> CHAT_PACKETS = Set.of(
        GameMessageS2CPacket.class,
        ChatMessageS2CPacket.class,
        ProfilelessChatMessageS2CPacket.class,
        OverlayMessageS2CPacket.class,
        TitleS2CPacket.class,
        SubtitleS2CPacket.class,
        CustomPayloadS2CPacket.class
    );

    private State state = State.IDLE;
    private int resumeTicksLeft;
    private boolean seenBackupKeyword;
    private SavedTrip pendingTrip;

    public TripResumer()
    {
        super(Addon.CATEGORY, "trip-resumer", "Persists the current baritone goal across server restarts and resumes the trip automatically once you are back on the main server.");
    }

    @Override
    public void onActivate()
    {
        pendingTrip = loadSavedTrip();
        classifyAndScheduleIfReady();
    }

    @Override
    public void onDeactivate()
    {
        state = State.IDLE;
        resumeTicksLeft = 0;
        pendingTrip = null;
        // IMPORTANT: do NOT delete trip.json here. Meteor calls onDeactivate on EVERY game-leave
        // / relogin (Modules.onGameLeft + Modules.onGameJoined -> onActivate). If we deleted the
        // file then, onActivate would reload null and the main keyword would never match on the
        // next re-entry. The file is only overwritten by a disconnect capture and removed after a
        // successful resume.
    }

    @EventHandler
    private void onTick(TickEvent.Post event)
    {
        if (state == State.PENDING_RESUME)
        {
            resumeTicksLeft--;
            if (resumeTicksLeft <= 0) resumeTrip();
        }
    }

    @EventHandler
    private void onJoin(GameJoinedEvent event)
    {
        seenBackupKeyword = false;
        if (pendingTrip == null) pendingTrip = loadSavedTrip();
        classifyAndScheduleIfReady();
    }

    @EventHandler
    private void onDisconnect(GameLeftEvent event)
    {
        if (pendingTrip == null)
        {
            SavedTrip captured = captureTrip();
            if (captured != null)
            {
                pendingTrip = captured;
                saveTrip(captured);
                info("Saved trip towards (x=%d, z=%d) to resume after reconnecting.", captured.x, captured.z);
            }
        }
        state = State.IDLE;
        resumeTicksLeft = 0;
    }

    @EventHandler
    private void onMessageReceive(ReceiveMessageEvent event)
    {
        handleChatText(event.getMessage().getString());
    }

    // Diagnostic: when debug-log is on, dump every chat-capable inbound packet (and any
    // packet whose text mentions the main keyword) so we can find which packet actually
    // carries 6b6t's "You're now playing on ..." line.
    @EventHandler
    private void onPacketReceive(PacketEvent.Receive event)
    {
        if (!debugLog.get()) return;

        String text = event.packet.toString();
        String keyword = mainChatKeyword.get();
        boolean matches = false;
        if (CHAT_PACKETS.contains(event.packet.getClass()))
        {
            matches = true;
        }
        else if (text.contains("playing on") || (!keyword.isEmpty() && text.contains(keyword)))
        {
            matches = true;
        }
        if (!matches) return;

        String truncated = text.length() > 400 ? text.substring(0, 400) + "..." : text;
        Addon.LOG.info("[TripResumer] packet {} -> {}", event.packet.getClass().getSimpleName(), truncated);
    }

    // Called from ClientPacketListenerMixin for every raw chat packet, including
    // action-bar overlays which never reach ChatComponent.addMessage and therefore
    // never trigger ReceiveMessageEvent (e.g. 6b6t's "You're now playing on ...").
    public static void onPacketChat(String text)
    {
        if (Modules.get() == null) return;
        TripResumer module = Modules.get().get(TripResumer.class);
        if (module != null && module.isActive()) module.handleChatText(text);
    }

    private void handleChatText(String rawText)
    {
        if (pendingTrip == null) pendingTrip = loadSavedTrip();
        if (pendingTrip == null) return;

        String text = normalize(rawText);

        String backupKw = backupChatKeyword.get();
        if (!backupKw.isEmpty() && keywordMatches(text, backupKw))
        {
            seenBackupKeyword = true;
            if (state == State.PENDING_RESUME)
            {
                state = State.ARMED;
                resumeTicksLeft = 0;
                info("Backup server detected, trip put on hold.");
            }
            return;
        }

        String mainKw = mainChatKeyword.get();
        boolean matched = false;
        if (!mainKw.isEmpty() && keywordMatches(text, mainKw))
        {
            matched = true;
            // The chat keyword is the trigger. No ARMED/IDLE state gating:
            // if a trip is pending (in memory or on disk) and the keyword shows up, resume.
            if (state != State.PENDING_RESUME)
            {
                state = State.PENDING_RESUME;
                resumeTicksLeft = resumeDelay.get();
                info("Main server confirmed, resuming the trip shortly.");
            }
        }

        if (debugLog.get())
        {
            Addon.LOG.info("[TripResumer] chat=|{}| mainKw=|{}| matched={} state={} pending={}x{}", rawText, mainKw, matched, state, pendingTrip != null ? pendingTrip.x : -1, pendingTrip != null ? pendingTrip.z : -1);
        }
    }

    // Matches the (normalized) keyword against the (normalized) chat text.
    // The keyword is treated as a regular-expression search, and falls back to a literal
    // substring search if it is not a valid pattern.
    private static boolean keywordMatches(String text, String keyword)
    {
        String needle = normalize(keyword);
        if (needle.isEmpty()) return false;
        try
        {
            return Pattern.compile(needle).matcher(text).find();
        }
        catch (PatternSyntaxException e)
        {
            return text.contains(needle);
        }
    }

    // Normalizes text so keyword matching survives unicode/formatting differences:
    // lowercases, strips MC §-format codes, folds apostrophes/quotes to ASCII,
    // collapses whitespace runs.
    private static String normalize(String s)
    {
        StringBuilder sb = new StringBuilder(s.length());
        for (int i = 0; i < s.length(); i++)
        {
            char c = s.charAt(i);
            if (c == '§')
            {
                i++;
                continue;
            }
            c = switch (c)
            {
                case '\u2018', '\u2019', '\u201A', '\u201B', '\u02BC', '\u2032' -> '\'';
                case '\u201C', '\u201D', '\u201E', '\u201F', '\u2033' -> '"';
                case '\u00A0', '\u2007', '\u202F' -> ' ';
                default -> c;
            };
            if (Character.isWhitespace(c))
            {
                if (sb.length() > 0 && sb.charAt(sb.length() - 1) != ' ') sb.append(' ');
                continue;
            }
            sb.append(Character.toLowerCase(c));
        }
        int end = sb.length();
        while (end > 0 && sb.charAt(end - 1) == ' ') end--;
        return sb.substring(0, end);
    }

    private void classifyAndScheduleIfReady()
    {
        if (mc.player == null || pendingTrip == null) return;

        String ip = mc.getCurrentServerEntry() != null ? mc.getCurrentServerEntry().address : "";
        String backup = backupServer.get();
        String main = mainServer.get();

        if (!backup.isEmpty() && containsIgnoreCase(ip, backup))
        {
            arm("on the backup server");
        }
        else if (requireMainKeyword.get())
        {
            arm("waiting for the main-server keyword in chat");
        }
        else
        {
            boolean isMain = main.isEmpty() || containsIgnoreCase(ip, main);
            if (isMain)
            {
                scheduleResume();
            }
            else if (resumeOnUnknown.get())
            {
                scheduleResume();
            }
            else
            {
                arm("on an unrecognized server");
            }
        }
    }

    private void scheduleResume()
    {
        state = State.PENDING_RESUME;
        resumeTicksLeft = resumeDelay.get();
        info("Trip saved (from %s), resuming towards (x=%d, z=%d) shortly.", pendingTrip.origin, pendingTrip.x, pendingTrip.z);
    }

    private void arm(String reason)
    {
        state = State.ARMED;
        resumeTicksLeft = 0;
        info("Trip saved (from %s, towards x=%d z=%d), currently %s.", pendingTrip.origin, pendingTrip.x, pendingTrip.z, reason);
    }

    private void resumeTrip()
    {
        if (pendingTrip == null || mc.player == null)
        {
            state = State.ARMED;
            return;
        }

        try
        {
            Goal goal = pendingTrip.toGoal();
            if (goal == null)
            {
                error("Couldn't reconstruct the saved goal, skipping resume.");
                state = State.ARMED;
                return;
            }

            IBaritone baritone = BaritoneAPI.getProvider().getPrimaryBaritone();
            if (pendingTrip.elytra)
            {
                BaritoneAPI.getSettings().elytraTermsAccepted.value = true;
                baritone.getCustomGoalProcess().setGoal(goal);
                baritone.getCommandManager().execute("elytra");
                info("Elytra trip resumed towards (x=%d, z=%d).", pendingTrip.x, pendingTrip.z);
            }
            else
            {
                baritone.getCustomGoalProcess().setGoalAndPath(goal);
                info("Trip resumed towards (x=%d, z=%d).", pendingTrip.x, pendingTrip.z);
            }

            pendingTrip = null;
            deleteSavedTrip();
            state = State.IDLE;
        }
        catch (Throwable t)
        {
            error("Failed to resume trip: %s", t.getClass().getSimpleName());
            state = State.ARMED;
        }
    }

    private SavedTrip captureTrip()
    {
        try
        {
            IBaritone baritone = BaritoneAPI.getProvider().getPrimaryBaritone();
            String origin = mc.getCurrentServerEntry() != null ? mc.getCurrentServerEntry().address : "unknown";
            String dimension = mc.world != null ? mc.world.getRegistryKey().getValue().toString() : "unknown";

            if (baritone.getElytraProcess().currentDestination() != null)
            {
                BlockPos dest = baritone.getElytraProcess().currentDestination();
                return SavedTrip.gxz(origin, dimension, true, dest.getX(), dest.getZ());
            }

            Goal goal = baritone.getCustomGoalProcess().getGoal();
            if (goal == null) return null;

            if (goal instanceof GoalXZ gx)
            {
                return SavedTrip.gxz(origin, dimension, false, gx.getX(), gx.getZ());
            }
            if (goal instanceof GoalBlock gb)
            {
                BlockPos p = gb.getGoalPos();
                return SavedTrip.gb(origin, dimension, false, p.getX(), p.getY(), p.getZ());
            }
            if (goal instanceof GoalNear gn)
            {
                BlockPos p = gn.getGoalPos();
                return SavedTrip.gb(origin, dimension, false, p.getX(), p.getY(), p.getZ());
            }

            return SavedTrip.gxz(origin, dimension, false, mc.player.getBlockPos().getX(), mc.player.getBlockPos().getZ());
        }
        catch (Throwable t)
        {
            return null;
        }
    }

    private File tripFile()
    {
        return new File(new File(MeteorClient.FOLDER, "TripResumer"), "trip.json");
    }

    private void saveTrip(SavedTrip trip)
    {
        try
        {
            File file = tripFile();
            file.getParentFile().mkdirs();
            Writer writer = new FileWriter(file);
            GSON.toJson(trip, writer);
            writer.close();
        }
        catch (IOException e)
        {
            error("Failed to save trip: %s", e.getMessage());
        }
    }

    private SavedTrip loadSavedTrip()
    {
        File file = tripFile();
        if (!file.exists()) return null;
        try
        {
            Reader reader = new FileReader(file);
            SavedTrip trip = GSON.fromJson(reader, SavedTrip.class);
            reader.close();
            return trip;
        }
        catch (IOException e)
        {
            return null;
        }
    }

    private void deleteSavedTrip()
    {
        tripFile().delete();
    }

    private static boolean containsIgnoreCase(String haystack, String needle)
    {
        return haystack.toLowerCase().contains(needle.toLowerCase());
    }

    static class SavedTrip
    {
        public String origin;
        public String dimension;
        public boolean elytra;
        public String kind;
        public int x;
        public int y;
        public int z;

        SavedTrip() {}

        static SavedTrip gxz(String origin, String dimension, boolean elytra, int x, int z)
        {
            SavedTrip trip = new SavedTrip();
            trip.origin = origin;
            trip.dimension = dimension;
            trip.elytra = elytra;
            trip.kind = "gxz";
            trip.x = x;
            trip.z = z;
            return trip;
        }

        static SavedTrip gb(String origin, String dimension, boolean elytra, int x, int y, int z)
        {
            SavedTrip trip = gxz(origin, dimension, elytra, x, z);
            trip.kind = "gb";
            trip.y = y;
            return trip;
        }

        Goal toGoal()
        {
            if (kind == null) return null;
            if (kind.equals("gxz")) return new GoalXZ(x, z);
            if (kind.equals("gb")) return new GoalBlock(x, y, z);
            return null;
        }
    }
}