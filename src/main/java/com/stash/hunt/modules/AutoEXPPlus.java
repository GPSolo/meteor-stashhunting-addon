/*
 * This file is part of the Meteor Client distribution (https://github.com/MeteorDevelopment/meteor-client).
 * Copyright (c) Meteor Development.
 */

package com.stash.hunt.modules;

import baritone.api.BaritoneAPI;
import baritone.api.IBaritone;
import baritone.api.pathing.goals.Goal;
import baritone.api.pathing.goals.GoalBlock;
import com.stash.hunt.Addon;
import meteordevelopment.meteorclient.events.world.TickEvent;
import meteordevelopment.meteorclient.settings.*;
import meteordevelopment.meteorclient.systems.modules.Module;
import meteordevelopment.meteorclient.systems.modules.Modules;
import meteordevelopment.meteorclient.systems.modules.movement.Scaffold;
import meteordevelopment.meteorclient.systems.modules.movement.elytrafly.ElytraFly;
import meteordevelopment.meteorclient.systems.modules.movement.elytrafly.ElytraFlightModes;
import meteordevelopment.meteorclient.utils.Utils;
import meteordevelopment.meteorclient.utils.player.FindItemResult;
import meteordevelopment.meteorclient.utils.player.InvUtils;
import meteordevelopment.meteorclient.utils.player.Rotations;
import meteordevelopment.meteorclient.utils.player.SlotUtils;
import meteordevelopment.orbit.EventHandler;
import net.minecraft.block.BlockState;
import net.minecraft.enchantment.Enchantments;
import net.minecraft.entity.EquipmentSlot;
import net.minecraft.item.ItemStack;
import net.minecraft.item.Items;
import net.minecraft.util.Hand;
import net.minecraft.util.math.BlockPos;
import net.minecraft.util.math.Vec3d;
import java.util.ArrayList;
import java.util.List;

public class AutoEXPPlus extends Module {
    public enum LandingMethod {
        BARITONE,
        SCAFFOLD,
        ELYTRAFLY
    }

    private final SettingGroup sgGeneral = settings.getDefaultGroup();

    private final Setting<Mode> mode = sgGeneral.add(new EnumSetting.Builder<Mode>()
        .name("mode")
        .description("Which items to repair.")
        .defaultValue(Mode.Both)
        .build()
    );

    private final Setting<Boolean> replenish = sgGeneral.add(new BoolSetting.Builder()
        .name("replenish")
        .description("Automatically replenishes exp into a selected hotbar slot.")
        .defaultValue(true)
        .build()
    );

    private final Setting<Integer> slot = sgGeneral.add(new IntSetting.Builder()
        .name("exp-slot")
        .description("The slot to replenish exp into.")
        .visible(replenish::get)
        .defaultValue(6)
        .range(1, 9)
        .sliderRange(1, 9)
        .build()
    );

    private final Setting<Integer> minThreshold = sgGeneral.add(new IntSetting.Builder()
        .name("min-threshold")
        .description("The minimum durability percentage that an item needs to fall to, to be repaired.")
        .defaultValue(30)
        .range(1, 100)
        .sliderRange(1, 100)
        .build()
    );

    private final Setting<Integer> maxThreshold = sgGeneral.add(new IntSetting.Builder()
        .name("max-threshold")
        .description("The maximum durability percentage to repair items to.")
        .defaultValue(80)
        .range(1, 100)
        .sliderRange(1, 100)
        .build()
    );

    private final Setting<Boolean> ignoreElytra = sgGeneral.add(new BoolSetting.Builder()
        .name("ignore-elytra")
        .description("Ignore elytra when repairing.")
        .defaultValue(false)
        .build()
    );

    private final Setting<Boolean> pauseBaritone = sgGeneral.add(new BoolSetting.Builder()
        .name("pause-baritone")
        .description("Stops the baritone process before repairing, remembers its current goal, and sets the goal back afterwards. Works for elytra and walking paths.")
        .defaultValue(true)
        .build()
    );

    private final Setting<Boolean> repairOnlyOnGround = sgGeneral.add(new BoolSetting.Builder()
        .name("repair-only-on-ground")
        .description("Only throws experience bottles while the player is standing on the ground (or in water). If the player is still moving/falling after landing it will wait.")
        .defaultValue(true)
        .build()
    );

    private final Setting<LandingMethod> landingMethod = sgGeneral.add(new EnumSetting.Builder<LandingMethod>()
        .name("landing-method")
        .description("How to get the player to the ground before repairing. Baritone paths an elytra flight down to the ground beneath you and is the most reliable. Scaffold builds a platform below the player with Meteor's Scaffold module while forcing the player to look up so they fall straight down onto it. ElytraFly uses the built-in ElytraFly module's auto-hover to lower the player onto a scaffold platform and keep them hovering while repairing, then resumes the flight via auto pilot.")
        .defaultValue(LandingMethod.BARITONE)
        .build()
    );

    private final Setting<Boolean> detectElytraFly = sgGeneral.add(new BoolSetting.Builder()
        .name("detect-elytra-fly")
        .description("Automatically switches to the ElytraFly landing method whenever the built-in ElytraFly module is active and the player is flying with it. Only applies to landing, the configured landing-method is used for anything else.")
        .defaultValue(true)
        .build()
    );

    private final Setting<Integer> baritoneLandingTimeout = sgGeneral.add(new IntSetting.Builder()
        .name("baritone-landing-timeout")
        .description("How long to wait for baritone to put the player on the ground before giving up and waiting for a natural landing.")
        .defaultValue(20 * 20)
        .range(20, 20 * 60)
        .sliderRange(20, 20 * 30)
        .visible(() -> landingMethod.get() == LandingMethod.BARITONE)
        .build()
    );

    private final Setting<Double> scaffoldRadius = sgGeneral.add(new DoubleSetting.Builder()
        .name("scaffold-radius")
        .description("How big of a platform to build around the player. 1 = 3x3. Used with the Scaffold and ElytraFly landing methods.")
        .defaultValue(1)
        .min(0)
        .sliderMax(6)
        .visible(() -> landingMethod.get() == LandingMethod.SCAFFOLD || landingMethod.get() == LandingMethod.ELYTRAFLY)
        .build()
    );

    private final Setting<Integer> scaffoldTimeout = sgGeneral.add(new IntSetting.Builder()
        .name("scaffold-timeout")
        .description("How long to wait (while looking up and falling straight down) for the platform to be built before giving up.")
        .defaultValue(20 * 10)
        .range(20, 20 * 60)
        .sliderRange(20, 20 * 30)
        .visible(() -> landingMethod.get() == LandingMethod.SCAFFOLD || landingMethod.get() == LandingMethod.ELYTRAFLY)
        .build()
    );

    private final Setting<Integer> elytraLandTimeout = sgGeneral.add(new IntSetting.Builder()
        .name("elytra-land-timeout")
        .description("How long to wait for auto-hold and the scaffold platform to lower the player before giving up. Only used with the ElytraFly landing method.")
        .defaultValue(20 * 20)
        .range(20, 20 * 60)
        .sliderRange(20, 20 * 30)
        .visible(() -> landingMethod.get() == LandingMethod.ELYTRAFLY)
        .build()
    );

    private final Setting<Boolean> pauseMovementModules = sgGeneral.add(new BoolSetting.Builder()
        .name("pause-movement-modules")
        .description("Disables modules that move the player (AFKVanillaFly, ElytraFlyPlusPlus, GotoPosition, Pitch40Util, TrailFollower, TrailMaker) while repairing and re-enables them afterwards.")
        .defaultValue(true)
        .build()
    );

    private enum Phase {
        NONE,
        PAUSE,
        LANDING,
        REPAIR
    }

    private enum ElytraFlyPhase {
        STOPPING,
        SCAFFOLD,
        HOVER
    }

    private static final List<Class<? extends Module>> MOVEMENT_MODULES = List.of(
        AFKVanillaFly.class,
        ElytraFlyPlusPlus.class,
        GotoPosition.class,
        Pitch40Util.class,
        TrailFollower.class,
        TrailMaker.class
    );

    private int repairingI = -1;
    private Phase phase = Phase.NONE;
    private int pauseTicks = 0;
    private int landingTicks = 0;
    private int landedTicks = 0;
    private boolean landingStarted = false;
    private boolean landingFailed = false;
    private float oldXRot = 0f;
    private LandingMethod activeLandingMethod = LandingMethod.BARITONE;
    private boolean canRestartFlight = false;

    // Baritone state captured before stopping so the goal can be restored after repair
    private boolean baritoneWasActive = false;
    private boolean baritoneWasElytra = false;
    private Goal storedGoal = null;

    private boolean scaffoldEnabled = false;
    private boolean scaffoldWasActive = false;
    private Boolean oldAirPlace = null;
    private Double oldRadius = null;
    private Integer oldBlocksPerTick = null;
    private final List<Module> disabledDuringRepair = new ArrayList<>();

    // ElytraFly landing state
    private boolean elytraScaffoldEnabled = false;
    private ElytraFly elytraFly = null;
    private ElytraFlyPhase elytraPhase = ElytraFlyPhase.STOPPING;
    private ElytraFlightModes oldElytraFlightMode = null;
    private boolean oldElytraAutoPilot = false;
    private boolean oldElytraAutoHover = false;
    private boolean oldElytraUseFireworks = false;
    private boolean oldElytraKeyShift = false;
    private boolean oldElytraKeyUp = false;

    public AutoEXPPlus() {
        super(Addon.CATEGORY, "auto-exp-plus", "Automatically repairs your armor and tools in pvp.");
    }

    @Override
    public void onActivate() {
        repairingI = -1;
        phase = Phase.NONE;
    }

    @Override
    public void onDeactivate() {
        finishRepair();
    }

    @EventHandler
    private void onTick(TickEvent.Pre event) {
        if (phase == Phase.NONE) {
            findRepairTarget();
            if (repairingI != -1) {
                startRepair();
            }
            return;
        }

        switch (phase) {
            case PAUSE -> {
                if (++pauseTicks < 10) return;
                pauseTicks = 0;
                landingTicks = 0;
                landedTicks = 0;
                landingStarted = false;
                landingFailed = false;
                canRestartFlight = false;
                activeLandingMethod = effectiveLandingMethod();
                phase = Phase.LANDING;
            }
            case LANDING -> {
                landingTicks++;

                switch (activeLandingMethod) {
                    case BARITONE -> baritoneLanding();
                    case SCAFFOLD -> scaffoldLanding();
                    case ELYTRAFLY -> elytraFlyLanding();
                }
            }
            case REPAIR -> {
                if (!needsRepair(mc.player.getInventory().getStack(repairingI), maxThreshold.get())) {
                    repairingI = -1;
                    finishRepair();
                    return;
                }
                if (!repairOnlyOnGround.get() || isLanded()) {
                    throwExperience();
                }
            }
        }
    }

    private void findRepairTarget() {
        repairingI = -1;

        if (mode.get() != Mode.Hands) {
            for (EquipmentSlot slot : new EquipmentSlot[] { EquipmentSlot.HEAD, EquipmentSlot.CHEST, EquipmentSlot.LEGS, EquipmentSlot.FEET }) {
                ItemStack stack = mc.player.getEquippedStack(slot);
                if (needsRepair(stack, minThreshold.get())) {
                    repairingI = SlotUtils.ARMOR_START + slot.getEntitySlotId();
                    return;
                }
            }
        }

        if (mode.get() != Mode.Armor && repairingI == -1) {
            for (Hand hand : Hand.values()) {
                if (needsRepair(mc.player.getStackInHand(hand), minThreshold.get())) {
                    repairingI = hand == Hand.MAIN_HAND ? mc.player.getInventory().selectedSlot : SlotUtils.OFFHAND;
                    return;
                }
            }
        }
    }

    private void startRepair() {
        if (pauseBaritone.get()) {
            captureAndStopBaritone();
        }
        if (pauseMovementModules.get()) {
            pauseMovementModules();
        }
        pauseTicks = 0;
        phase = Phase.PAUSE;
    }

    private void finishRepair() {
        disableScaffold();
        if (activeLandingMethod == LandingMethod.ELYTRAFLY && elytraFly != null) {
            if (canRestartFlight) {
                restoreElytraFly();
            } else {
                stopElytraFlyLanding();
            }
        }
        mc.player.setPitch(oldXRot);
        restoreMovementModules();
        restoreBaritone();
        phase = Phase.NONE;
    }

    private void throwExperience() {
        FindItemResult exp = InvUtils.find(Items.EXPERIENCE_BOTTLE);

        if (exp.found()) {
            if (!exp.isHotbar() && !exp.isOffhand()) {
                if (!replenish.get()) return;
                InvUtils.move().from(exp.slot()).toHotbar(slot.get() - 1);
            }

            Rotations.rotate(mc.player.getYaw(), 90, () -> {
                if (exp.getHand() != null) {
                    mc.interactionManager.interactItem(mc.player, exp.getHand());
                }
                else {
                    InvUtils.swap(exp.slot(), true);
                    mc.interactionManager.interactItem(mc.player, Hand.MAIN_HAND);
                    InvUtils.swapBack();
                }
            });
        }
    }

    /**
     * Records the current baritone goal (walking or elytra) and fully stops the process.
     * The goal is stored so {@link #restoreBaritone()} can resume pathing to the same point.
     */
    private void captureAndStopBaritone() {
        baritoneWasActive = false;
        baritoneWasElytra = false;
        storedGoal = null;
        try {
            Class.forName("baritone.api.BaritoneAPI");
            IBaritone baritone = BaritoneAPI.getProvider().getPrimaryBaritone();

            // Capture the goal before stopping so it can be restored later
            Goal goal = baritone.getPathingBehavior().getGoal();
            if (goal == null) {
                goal = baritone.getCustomGoalProcess().mostRecentGoal();
            }
            if (goal != null) {
                storedGoal = goal;
                baritoneWasElytra = baritone.getElytraProcess().currentDestination() != null;
                baritoneWasActive = true;
            }

            // Actually stop the process (cancels everything, clears the goal)
            baritone.getCommandManager().execute("stop");
        }
        catch (Throwable t) {
            info("Baritone not found, skipping stop.");
        }
    }

    /**
     * Restores the goal that was active before baritone was stopped, either through the
     * elytra process (firework flight) or the custom goal process (walking path).
     */
    private void restoreBaritone() {
        if (!baritoneWasActive || storedGoal == null) {
            baritoneWasActive = false;
            storedGoal = null;
            return;
        }
        try {
            Class.forName("baritone.api.BaritoneAPI");
            IBaritone baritone = BaritoneAPI.getProvider().getPrimaryBaritone();
            BaritoneAPI.getSettings().elytraTermsAccepted.value = true;

            if (baritoneWasElytra) {
                // Let baritone handle the takeoff: register the goal then run the #elytra
                // command rather than scheduling a path directly
                baritone.getCustomGoalProcess().setGoal(storedGoal);
                BaritoneAPI.getSettings().elytraTermsAccepted.value = true;
                baritone.getCommandManager().execute("elytra");
            }
            else {
                baritone.getCustomGoalProcess().setGoalAndPath(storedGoal);
            }
            info("Baritone resumed to its previous goal.");
        }
        catch (Throwable t) {
            info("Baritone not found, skipping restore.");
        }
        baritoneWasActive = false;
        storedGoal = null;
    }

    /**
     * Starts the baritone landing: paths the elytra down to the ground directly below the
     * player, or for a walking path just re-focuses on the player's current position.
     */
    private void startBaritoneLanding() {
        try {
            Class.forName("baritone.api.BaritoneAPI");
            IBaritone baritone = BaritoneAPI.getProvider().getPrimaryBaritone();

            if (baritoneWasElytra) {
                BlockPos below = findGroundBelow(mc.player.getBlockPos());
                BaritoneAPI.getSettings().elytraTermsAccepted.value = true;
                baritone.getElytraProcess().pathTo(new GoalBlock(below.getX(), below.getY(), below.getZ()));
            }
            else {
                baritone.getCustomGoalProcess().setGoalAndPath(new GoalBlock(mc.player.getBlockPos()));
            }
            info("Baritone is finding a landing spot.");
        }
        catch (Throwable t) {
            landingFailed = true;
            baritoneWasActive = false; // nothing to restore after this
            info("Could not start baritone landing (" + t.getMessage() + ").");
        }
    }

    /**
     * Stops any baritone processing because the landing failed. Marks the trip as not
     * restorable so the original flight is not re-attempted after repair.
     */
    private void stopBaritoneWithoutRestore() {
        try {
            Class.forName("baritone.api.BaritoneAPI");
            BaritoneAPI.getProvider().getPrimaryBaritone().getCommandManager().execute("stop");
        }
        catch (Throwable ignored) {}
        baritoneWasActive = false;
    }

    private LandingMethod effectiveLandingMethod() {
        if (detectElytraFly.get() && isUsingElytraFly()) return LandingMethod.ELYTRAFLY;
        return landingMethod.get();
    }

    private boolean isUsingElytraFly() {
        ElytraFly module = Modules.get().get(ElytraFly.class);
        return module != null && module.isActive() && mc.player != null && mc.player.isGliding();
    }

    private void baritoneLanding() {
        if (!landingStarted) {
            landingStarted = true;
            startBaritoneLanding();
        }
        if (landingFailed) {
            // baritone landing could not start or timed out: wait for a natural landing,
            // and do not attempt to restart the trip afterwards
            phase = Phase.REPAIR;
        } else if (isLanded()) {
            if (++landedTicks >= 5) phase = Phase.REPAIR;
        } else {
            landedTicks = 0;
            if (landingTicks >= baritoneLandingTimeout.get()) {
                landingFailed = true;
                stopBaritoneWithoutRestore();
                info("Baritone could not find a landing, waiting for the player to touch down.");
                phase = Phase.REPAIR;
            }
        }
    }

    private void scaffoldLanding() {
        if (!landingStarted) {
            landingStarted = true;
            oldXRot = mc.player.getPitch();
            enableScaffold();
        }
        // Scaffold: keep looking straight up so the elytra stalls and the player
        // falls straight down onto the platform being built below them
        mc.player.setPitch(-90f);
        if (isLanded()) {
            if (++landedTicks >= 5) {
                disableScaffold();
                mc.player.setPitch(oldXRot);
                phase = Phase.REPAIR;
            }
        } else {
            landedTicks = 0;
            if (landingTicks >= scaffoldTimeout.get()) {
                disableScaffold();
                mc.player.setPitch(oldXRot);
                info("Could not land on the scaffold platform, waiting for the player to touch down.");
                phase = Phase.REPAIR;
            }
        }
    }

    private void elytraFlyLanding() {
        if (!landingStarted) {
            landingStarted = true;
            oldXRot = mc.player.getPitch();
            startElytraFlyLanding();
        }
        if (landingFailed) {
            stopElytraFlyLanding();
            phase = Phase.REPAIR;
            return;
        }

        switch (elytraPhase) {
            case STOPPING -> {
                if (isElytraStopped()) {
                    elytraPhase = ElytraFlyPhase.SCAFFOLD;
                } else if (landingTicks >= elytraLandTimeout.get()) {
                    landingFailed = true;
                    info("ElytraFly did not stop in time, waiting for the player to touch down.");
                }
            }
            case SCAFFOLD -> {
                if (!elytraScaffoldEnabled) {
                    enableScaffold();
                    elytraScaffoldEnabled = true;
                }
                if (mc.player.isOnGround() || mc.player.isTouchingWater()) {
                    disableScaffold();
                    elytraScaffoldEnabled = false;
                    mc.player.setPitch(oldXRot);
                    canRestartFlight = true;
                    phase = Phase.REPAIR;
                } else if (platformBuiltBelow()) {
                    disableScaffold();
                    elytraScaffoldEnabled = false;
                    enableElytraHover();
                    elytraPhase = ElytraFlyPhase.HOVER;
                } else if (landingTicks >= elytraLandTimeout.get()) {
                    landingFailed = true;
                    info("Could not build a platform below the player, waiting for the player to touch down.");
                }
            }
            case HOVER -> {
                if (isElytraHovering() || mc.player.isOnGround() || mc.player.isTouchingWater()) {
                    if (++landedTicks >= 5) {
                        canRestartFlight = true;
                        phase = Phase.REPAIR;
                    }
                } else {
                    landedTicks = 0;
                    if (landingTicks >= elytraLandTimeout.get()) {
                        landingFailed = true;
                        info("Could not hover on the platform, waiting for the player to touch down.");
                    }
                }
            }
        }
    }

    private void startElytraFlyLanding() {
        elytraFly = Modules.get().get(ElytraFly.class);
        if (elytraFly == null || !elytraFly.isActive()) {
            landingFailed = true;
            info("ElytraFly module is not active, waiting for the player to touch down.");
            return;
        }

        elytraPhase = ElytraFlyPhase.STOPPING;
        oldElytraAutoPilot = elytraFly.autoPilot.get();
        oldElytraAutoHover = elytraFly.autoHover.get();
        oldElytraUseFireworks = elytraFly.useFireworks.get();
        oldElytraFlightMode = elytraFly.flightMode.get();
        oldElytraKeyShift = mc.options.sneakKey.isPressed();
        oldElytraKeyUp = mc.options.forwardKey.isPressed();

        // Stop auto piloting forwards and disable firework boosting
        elytraFly.autoPilot.set(false);
        elytraFly.useFireworks.set(false);
        elytraFly.autoHover.set(false);
        mc.options.forwardKey.setPressed(false);
        mc.options.sneakKey.setPressed(false);

        // auto-hover is incompatible with the Bounce flight mode; temporarily switch to Vanilla
        if (oldElytraFlightMode == ElytraFlightModes.Bounce) {
            elytraFly.flightMode.set(ElytraFlightModes.Vanilla);
        }
    }

    private boolean isElytraStopped() {
        if (mc.player == null || mc.world == null) return false;
        if (mc.player.isOnGround()) return true;
        Vec3d v = mc.player.getVelocity();
        return Math.abs(v.x) < 0.1 && Math.abs(v.z) < 0.1;
    }

    private boolean platformBuiltBelow() {
        if (mc.player == null || mc.world == null) return false;
        if (!mc.player.isGliding()) return false;
        BlockPos below = mc.player.getBlockPos().down();
        BlockState state = mc.world.getBlockState(below);
        // Player must still be clearly above the placed platform so auto-hover can lower them onto it
        return state.isSolid() && mc.player.getPos().y > below.getY() + 1.05;
    }

    private void enableElytraHover() {
        if (elytraFly == null) return;
        elytraFly.autoHover.set(true);
        mc.options.sneakKey.setPressed(true);
    }

    private void disableElytraHover() {
        if (elytraFly != null) elytraFly.autoHover.set(false);
        mc.options.sneakKey.setPressed(false);
    }

    private boolean isElytraHovering() {
        if (mc.player == null || mc.world == null) return false;
        if (!mc.player.isGliding()) return false;
        BlockPos below = mc.player.getBlockPos().down();
        if (!mc.world.getBlockState(below).isSolid()) return false;
        double hoverY = below.getY() + 1.34;
        return Math.abs(mc.player.getPos().y - hoverY) < 0.5;
    }

    /**
     * Disables everything the ElytraFly landing method did and does not resume the flight.
     */
    private void stopElytraFlyLanding() {
        disableScaffold();
        elytraScaffoldEnabled = false;
        disableElytraHover();
        if (elytraFly != null) {
            elytraFly.autoPilot.set(false);
            elytraFly.useFireworks.set(false);
            if (oldElytraFlightMode != null) elytraFly.flightMode.set(oldElytraFlightMode);
        }
        mc.options.sneakKey.setPressed(false);
        mc.options.forwardKey.setPressed(false);
        canRestartFlight = false;
        elytraPhase = ElytraFlyPhase.STOPPING;
    }

    /**
     * Restores the built-in ElytraFly module to its pre-repair state so the trip can continue.
     */
    private void restoreElytraFly() {
        if (elytraFly == null) return;
        disableElytraHover();
        elytraFly.autoPilot.set(oldElytraAutoPilot);
        elytraFly.useFireworks.set(oldElytraUseFireworks);
        if (oldElytraFlightMode != null) {
            ElytraFlightModes current = elytraFly.flightMode.get();
            if (current != oldElytraFlightMode && current == ElytraFlightModes.Vanilla) {
                elytraFly.flightMode.set(oldElytraFlightMode);
            }
        }
        mc.options.sneakKey.setPressed(oldElytraKeyShift);
        mc.options.forwardKey.setPressed(oldElytraKeyUp);
        info("ElytraFly restored (autoPilot=" + oldElytraAutoPilot + ", autoHover=" + oldElytraAutoHover + ")");
        elytraFly = null;
        elytraPhase = ElytraFlyPhase.STOPPING;
        elytraScaffoldEnabled = false;
        oldElytraFlightMode = null;
    }

    private BlockPos findGroundBelow(BlockPos start) {
        BlockPos.Mutable pos = start.mutableCopy();
        int y = Math.min(start.getY(), mc.world.getTopYInclusive());
        while (y > mc.world.getBottomY()) {
            if (!mc.world.getBlockState(pos.setY(y)).isAir()) {
                return new BlockPos(start.getX(), y + 1, start.getZ());
            }
            y--;
        }
        return new BlockPos(start.getX(), mc.world.getBottomY() + 1, start.getZ());
    }

    private boolean isLanded() {
        if (mc.player == null || mc.world == null) return false;
        if (mc.player.isOnGround() || mc.player.isTouchingWater()) return true;
        return activeLandingMethod == LandingMethod.ELYTRAFLY && isElytraHovering();
    }

    private void pauseMovementModules() {
        disabledDuringRepair.clear();
        for (Class<? extends Module> moduleClass : MOVEMENT_MODULES) {
            Module module = Modules.get().get(moduleClass);
            if (module != null && module.isActive()) {
                module.toggle();
                disabledDuringRepair.add(module);
            }
        }
    }

    private void restoreMovementModules() {
        for (Module module : disabledDuringRepair) {
            if (module != null && !module.isActive()) {
                module.toggle();
            }
        }
        disabledDuringRepair.clear();
    }

    private void enableScaffold() {
        if (scaffoldEnabled) return;
        Module module = Modules.get().get(Scaffold.class);
        if (module == null) return;

        scaffoldWasActive = module.isActive();
        try {
            Setting airPlace = module.settings.get("air-place");
            Setting radius = module.settings.get("radius");
            Setting blocksPerTick = module.settings.get("blocks-per-tick");

            if (airPlace != null) oldAirPlace = (Boolean) airPlace.get();
            if (radius != null) oldRadius = (Double) radius.get();
            if (blocksPerTick != null) oldBlocksPerTick = (Integer) blocksPerTick.get();

            if (airPlace != null) airPlace.set(true);
            if (radius != null) radius.set(scaffoldRadius.get());
            if (blocksPerTick != null) blocksPerTick.set(3);
        }
        catch (Throwable ignored) {}

        if (!scaffoldWasActive) module.toggle();
        scaffoldEnabled = true;
    }

    private void disableScaffold() {
        if (!scaffoldEnabled) return;
        Module module = Modules.get().get(Scaffold.class);
        if (module != null) {
            try {
                Setting airPlace = module.settings.get("air-place");
                Setting radius = module.settings.get("radius");
                Setting blocksPerTick = module.settings.get("blocks-per-tick");
                if (airPlace != null && oldAirPlace != null) airPlace.set(oldAirPlace);
                if (radius != null && oldRadius != null) radius.set(oldRadius);
                if (blocksPerTick != null && oldBlocksPerTick != null) blocksPerTick.set(oldBlocksPerTick);
            }
            catch (Throwable ignored) {}

            if (!scaffoldWasActive && module.isActive()) module.toggle();
        }

        scaffoldWasActive = false;
        scaffoldEnabled = false;
        oldAirPlace = null;
        oldRadius = null;
        oldBlocksPerTick = null;
    }

    private boolean needsRepair(ItemStack itemStack, double threshold) {
        if (itemStack.isEmpty()) return false;
        return Utils.hasEnchantments(itemStack, Enchantments.MENDING) &&
            ((double) (itemStack.getMaxDamage() - itemStack.getDamage()) / itemStack.getMaxDamage()) * 100 <= threshold;
    }

    public enum Mode {
        Armor,
        Hands,
        Both
    }
}