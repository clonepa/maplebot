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
    async def bj(self, context):
        
        command = context.message.content.split()[1]
        user = context.message.author.id
    
        if command == "new":
            pass
        elif command == "help":
            pass
        
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
