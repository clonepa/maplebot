import sys
import logging
import sqlite3

from discord.ext import commands

from .. import brains, util, mapleclicker
logger = logging.getLogger('maple.debug')

class Mapleclicker():
    def __init__(self, bot):
        self.bot = bot
        self.reactables = []

    @commands.command(pass_context=True)
    async def maplemine(self, context):
        

        #command = context.message.content.split()[1]
        user = context.message.author.id
        
        new_mm = mapleclicker.ClickerMachine(self.bot, user)
        new_mm.msg = await self.bot.say("``` strike the earf ```")

        for emoji in new_mm.cmd_reactions_add:
                await self.bot.add_reaction(new_mm.msg, emoji)

        self.reactables += [new_mm]
        
        
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
    bot.add_cog(Mapleclicker(bot))
