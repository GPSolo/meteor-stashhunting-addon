package com.stash.hunt.mixin;

import com.stash.hunt.modules.TripResumer;
import net.minecraft.client.network.ClientPlayNetworkHandler;
import net.minecraft.network.packet.s2c.play.ChatMessageS2CPacket;
import net.minecraft.network.packet.s2c.play.GameMessageS2CPacket;
import net.minecraft.network.packet.s2c.play.OverlayMessageS2CPacket;
import net.minecraft.network.packet.s2c.play.ProfilelessChatMessageS2CPacket;
import net.minecraft.network.packet.s2c.play.SubtitleS2CPacket;
import net.minecraft.network.packet.s2c.play.TitleS2CPacket;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

@Mixin(ClientPlayNetworkHandler.class)
public class ClientPacketListenerMixin
{
    @Inject(at = @At("HEAD"), method = "onGameMessage")
    private void onSystemChat(GameMessageS2CPacket packet, CallbackInfo ci)
    {
        TripResumer.onPacketChat(packet.content().getString());
    }

    @Inject(at = @At("HEAD"), method = "onChatMessage")
    private void onPlayerChat(ChatMessageS2CPacket packet, CallbackInfo ci)
    {
        TripResumer.onPacketChat(packet.body().content());
    }

    @Inject(at = @At("HEAD"), method = "onProfilelessChatMessage")
    private void onDisguisedChat(ProfilelessChatMessageS2CPacket packet, CallbackInfo ci)
    {
        TripResumer.onPacketChat(packet.message().getString());
    }

    @Inject(at = @At("HEAD"), method = "onOverlayMessage")
    private void onActionBarText(OverlayMessageS2CPacket packet, CallbackInfo ci)
    {
        TripResumer.onPacketChat(packet.text().getString());
    }

    @Inject(at = @At("HEAD"), method = "onTitle")
    private void onTitleText(TitleS2CPacket packet, CallbackInfo ci)
    {
        TripResumer.onPacketChat(packet.text().getString());
    }

    @Inject(at = @At("HEAD"), method = "onSubtitle")
    private void onSubtitleText(SubtitleS2CPacket packet, CallbackInfo ci)
    {
        TripResumer.onPacketChat(packet.text().getString());
    }
}
