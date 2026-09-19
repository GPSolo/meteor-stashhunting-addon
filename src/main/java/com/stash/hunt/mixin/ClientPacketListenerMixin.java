package com.stash.hunt.mixin;

import com.stash.hunt.modules.TripResumer;
import net.minecraft.client.multiplayer.ClientPacketListener;
import net.minecraft.network.protocol.game.ClientboundDisguisedChatPacket;
import net.minecraft.network.protocol.game.ClientboundPlayerChatPacket;
import net.minecraft.network.protocol.game.ClientboundSetActionBarTextPacket;
import net.minecraft.network.protocol.game.ClientboundSetSubtitleTextPacket;
import net.minecraft.network.protocol.game.ClientboundSetTitleTextPacket;
import net.minecraft.network.protocol.game.ClientboundSystemChatPacket;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

@Mixin(ClientPacketListener.class)
public class ClientPacketListenerMixin
{
    @Inject(at = @At("HEAD"), method = "handleSystemChat")
    private void onSystemChat(ClientboundSystemChatPacket packet, CallbackInfo ci)
    {
        TripResumer.onPacketChat(packet.content().getString());
    }

    @Inject(at = @At("HEAD"), method = "handlePlayerChat")
    private void onPlayerChat(ClientboundPlayerChatPacket packet, CallbackInfo ci)
    {
        TripResumer.onPacketChat(packet.body().content());
    }

    @Inject(at = @At("HEAD"), method = "handleDisguisedChat")
    private void onDisguisedChat(ClientboundDisguisedChatPacket packet, CallbackInfo ci)
    {
        TripResumer.onPacketChat(packet.message().getString());
    }

    @Inject(at = @At("HEAD"), method = "setActionBarText")
    private void onActionBarText(ClientboundSetActionBarTextPacket packet, CallbackInfo ci)
    {
        TripResumer.onPacketChat(packet.text().getString());
    }

    @Inject(at = @At("HEAD"), method = "setTitleText")
    private void onTitleText(ClientboundSetTitleTextPacket packet, CallbackInfo ci)
    {
        TripResumer.onPacketChat(packet.text().getString());
    }

    @Inject(at = @At("HEAD"), method = "setSubtitleText")
    private void onSubtitleText(ClientboundSetSubtitleTextPacket packet, CallbackInfo ci)
    {
        TripResumer.onPacketChat(packet.text().getString());
    }
}
