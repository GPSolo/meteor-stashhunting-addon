package com.stash.hunt.mixin;

import com.stash.hunt.modules.TripResumer;
import net.minecraft.client.gui.components.ChatComponent;
import net.minecraft.client.multiplayer.chat.GuiMessage;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

@Mixin(ChatComponent.class)
public class ChatComponentMixin
{
    // logChatMessage is where the vanilla client writes every displayed chat line to the
    // console as "[System] [CHAT] ..." / "[CHAT] ...". Hooking it guarantees we see every
    // message that actually reaches the chat HUD, regardless of which packet type carried it
    // (6b6t's "You're now playing on worker-N" bypasses handleSystemChat/handlePlayerChat/
    // handleDisguisedChat/setActionBarText/setTitleText/setSubtitleText and never fires
    // Meteor's ReceiveMessageEvent, but it still gets logged here).
    @Inject(method = "logChatMessage", at = @At("HEAD"))
    private void onLogChatMessage(GuiMessage guiMessage, CallbackInfo ci)
    {
        TripResumer.onPacketChat(guiMessage.content().getString());
    }
}