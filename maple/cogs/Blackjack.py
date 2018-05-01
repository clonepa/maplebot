import sys
import logging
import sqlite3
import json

from discord.ext import commands

from .. import brains, util, blackjack
logger = logging.getLogger('maple.debug')

class Blackjack():
    def __init__(self, bot):
        self.bot = bot
        self.reactables = []
    @commands.command(pass_context=True)
    async def bj(self, context):
        
        command = context.message.content.split()[1]
        user = context.message.author.id
    
        if command == "new":
            new_bj = blackjack.BlackJackMachine(self.bot)
            new_bj.msg = await self.bot.say("```Pwease wait warmly... uwu```")
        
            for emoji in new_bj.cmd_reactions_add:
                await self.bot.add_reaction(new_bj.msg, emoji)

            await new_bj.update_msg()    
            self.reactables += [new_bj]
        elif command == "help":
            await self.bot.say("Blackjack Commands\n" +
                         "\U0001f60e - Join game. Unreact to this emoji to leave game (forfeit if playing hand).\n" +
                         "\U0001f1ed - Hit\n" +
                         "\U0001f1f8 - Stand\n" +
                         "\U0001f198 - Surrender\n" +
                         "\u2935 - Double Down\n" +
                         "\u25b6 \u23e9 \u23ed - Increase bet 10/50/200 maplecents\n" +
                         "\U0001f196 - Clear bet\n" +
                         "\U0001f171 - Accept bet")
        
    async def on_reaction_add(self, reaction, user):
        if user == self.bot.user:
            return
        for sweetbaby in self.reactables:
            if sweetbaby.msg.id != None and (sweetbaby.msg.id == reaction.message.id):
                await sweetbaby.parse_reaction_add(reaction, user)
    async def on_reaction_remove(self, reaction, user):
        if user == self.bot.user:
            return
        for sweetbaby in self.reactables:
            if sweetbaby.msg.id != None and (sweetbaby.msg.id == reaction.message.id):
                await sweetbaby.parse_reaction_remove(reaction, user)
    
def setup(bot):
    bot.add_cog(Blackjack(bot))
