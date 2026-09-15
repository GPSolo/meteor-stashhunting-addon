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
import meteordevelopment.meteorclient.utils.Utils;
import meteordevelopment.meteorclient.utils.player.FindItemResult;
import meteordevelopment.meteorclient.utils.player.InvUtils;
import meteordevelopment.meteorclient.utils.player.Rotations;
import meteordevelopment.meteorclient.utils.player.SlotUtils;
import meteordevelopment.orbit.EventHandler;
import net.minecraft.core.BlockPos;
import net.minecraft.world.InteractionHand;
import net.minecraft.world.entity.EquipmentSlot;
import net.minecraft.world.entity.EquipmentSlotGroup;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.Items;
import net.minecraft.world.item.enchantment.Enchantments;

import java.util.ArrayList;
import java.util.List;

public class AutoEXPPlus extends Module {
    public enum LandingMethod {
        BARITONE,
        SCAFFOLD
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
        .description("How to get the player to the ground before repairing. Baritone paths an elytra flight down to the ground beneath you and is the most reliable. Scaffold builds a platform below the player with Meteor's Scaffold module while forcing the player to look up so they fall straight down onto it.")
        .defaultValue(LandingMethod.BARITONE)
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
        .description("How big of a platform to build around the player. 1 = 3x3. Only used with the Scaffold landing method.")
        .defaultValue(1)
        .min(0)
        .sliderMax(6)
        .visible(() -> landingMethod.get() == LandingMethod.SCAFFOLD)
        .build()
    );

    private final Setting<Integer> scaffoldTimeout = sgGeneral.add(new IntSetting.Builder()
        .name("scaffold-timeout")
        .description("How long to wait (while looking up and falling straight down) for the platform to be built before giving up.")
        .defaultValue(20 * 10)
        .range(20, 20 * 60)
        .sliderRange(20, 20 * 30)
        .visible(() -> landingMethod.get() == LandingMethod.SCAFFOLD)
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
                phase = Phase.LANDING;
            }
            case LANDING -> {
                landingTicks++;

                if (landingMethod.get() == LandingMethod.BARITONE) {
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
                } else {
                    if (!landingStarted) {
                        landingStarted = true;
                        oldXRot = mc.player.getXRot();
                        enableScaffold();
                    }
                    // Scaffold: keep looking straight up so the elytra stalls and the player
                    // falls straight down onto the platform being built below them
                    mc.player.setXRot(-90f);
                    if (isLanded()) {
                        if (++landedTicks >= 5) {
                            disableScaffold();
                            mc.player.setXRot(oldXRot);
                            phase = Phase.REPAIR;
                        }
                    } else {
                        landedTicks = 0;
                        if (landingTicks >= scaffoldTimeout.get()) {
                            disableScaffold();
                            mc.player.setXRot(oldXRot);
                            info("Could not land on the scaffold platform, waiting for the player to touch down.");
                            phase = Phase.REPAIR;
                        }
                    }
                }
            }
            case REPAIR -> {
                if (!needsRepair(mc.player.getInventory().getItem(repairingI), maxThreshold.get())) {
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
            for (EquipmentSlot slot : EquipmentSlotGroup.ARMOR) {
                ItemStack stack = mc.player.getItemBySlot(slot);
                if (needsRepair(stack, minThreshold.get())) {
                    repairingI = SlotUtils.ARMOR_START + slot.getIndex();
                    return;
                }
            }
        }

        if (mode.get() != Mode.Armor && repairingI == -1) {
            for (InteractionHand hand : InteractionHand.values()) {
                if (needsRepair(mc.player.getItemInHand(hand), minThreshold.get())) {
                    repairingI = hand == InteractionHand.MAIN_HAND ? mc.player.getInventory().getSelectedSlot() : SlotUtils.OFFHAND;
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
        mc.player.setXRot(oldXRot);
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

            Rotations.rotate(mc.player.getYRot(), 90, () -> {
                if (exp.getHand() != null) {
                    mc.gameMode.useItem(mc.player, exp.getHand());
                }
                else {
                    InvUtils.swap(exp.slot(), true);
                    mc.gameMode.useItem(mc.player, InteractionHand.MAIN_HAND);
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
                BlockPos below = findGroundBelow(mc.player.blockPosition());
                BaritoneAPI.getSettings().elytraTermsAccepted.value = true;
                baritone.getElytraProcess().pathTo(new GoalBlock(below.getX(), below.getY(), below.getZ()));
            }
            else {
                baritone.getCustomGoalProcess().setGoalAndPath(new GoalBlock(mc.player.blockPosition()));
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

    private BlockPos findGroundBelow(BlockPos start) {
        BlockPos.MutableBlockPos pos = start.mutable();
        int y = Math.min(start.getY(), mc.level.getMaxY());
        while (y > mc.level.getMinY()) {
            if (!mc.level.getBlockState(pos.setY(y)).isAir()) {
                return new BlockPos(start.getX(), y + 1, start.getZ());
            }
            y--;
        }
        return new BlockPos(start.getX(), mc.level.getMinY() + 1, start.getZ());
    }

    private boolean isLanded() {
        if (mc.player == null || mc.level == null) return false;
        return mc.player.onGround() || mc.player.isInWater();
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
            ((double) (itemStack.getMaxDamage() - itemStack.getDamageValue()) / itemStack.getMaxDamage()) * 100 <= threshold;
    }

    public enum Mode {
        Armor,
        Hands,
        Both
    }
}