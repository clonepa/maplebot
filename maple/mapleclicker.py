import discord
import asyncio
import maple.brains

class ClickerMachine:

    def __init__(self, client, user):
    	self.msg = None
        self.client = client
        self.user = user
        self.microcents = 0
        self.cmd_reactions_add = {"\unicodeescapegoeshere": self.cmd_piddle}
        self.cmd_reactions_add = {"\unicodeescapegoeshere": self.cmd_piddle}
        self.state = 0 #decides art

    def cmd_piddle_add(self, user):
    	pass

    def cmd_piddle_remove(self, user):
    	pass
	
	async def parse_reaction_add(self, reaction, user):
    	print(reaction.emoji.encode("unicode_escape"), user.id)
    	valid = False
    	if user.id == self.user:
    		valid = self.cmd_reactions_add[reaction.emoji](user.id)

    	if valid:
            pass

    async def parse_reaction_remove(self, reaction, user):
    	print(reaction.emoji.encode("unicode_escape"), user.id)
    	valid = False
    	if user.id == self.user:
    		valid = self.cmd_reactions_remove[reaction.emoji](user.id)

    	if valid:
            pass