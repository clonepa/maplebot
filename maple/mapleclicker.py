import discord
import asyncio
import maple.brains
import random

class ClickerMachine:

	def __init__(self, client, user):
		self.msg = None
		self.client = client
		self.user = user
		self.user_name = maple.brains.get_record(user)['name']
		self.microcents = 0
		self.lifetime_microcents = 0
		self.cmd_reactions_add = {"\u26cf": self.cmd_piddle,
								  "\U0001f4b8": self.cmd_cashout}

		self.cmd_reactions_remove = {"\u26cf": self.cmd_piddle}
		self.state = 0 #decides art
		self.update_queued = False

		self.mine_bonus = 0

	def cmd_piddle(self, user):
		cents_to_add = random.randint(0,100000)

		cents_to_add = int(cents_to_add * (1 + self.mine_bonus/100))
		self.microcents += cents_to_add
		self.lifetime_microcents += cents_to_add
		if random.randint(1, 29) == 1:
			self.mine_bonus += random.randint(1,3)

		if self.update_queued == False:	
			asyncio.ensure_future(self.update_msg())

	def cmd_cashout(self, user):
		cashout_value = int(self.microcents / 1000000)
		self.microcents = self.microcents % 1000000
		maple.brains.adjust_cash(user,cashout_value / 100)
		if self.update_queued == False:	
			asyncio.ensure_future(self.update_msg())

	async def parse_reaction_add(self, reaction, user):
		#print(reaction.emoji.encode("unicode_escape"), user.id)
		valid = False
		if reaction.emoji not in self.cmd_reactions_add:
			return False
		if user.id == self.user:
			valid = self.cmd_reactions_add[reaction.emoji](user.id)

		if reaction.emoji != "\u26cf":
			await self.client.remove_reaction(self.msg, reaction.emoji, user)


		if valid:
			pass


	async def parse_reaction_remove(self, reaction, user):
		#print(reaction.emoji.encode("unicode_escape"), user.id)
		valid = False
		if reaction.emoji not in self.cmd_reactions_remove:
			return False
		if user.id == self.user:
			valid = self.cmd_reactions_remove[reaction.emoji](user.id)
		if valid:
			pass



	def print_state(self):

		user_header = self.user_name + " is mining in this hole..."
		current_haul = "{:,}".format(self.microcents)
		total_haul =  "{:,}".format(self.lifetime_microcents)
		if self.microcents > 1000000:
			str_cashout = "	[CASHOUT AVAILABLE]"
		else:
			str_cashout = ""

		outstring = user_header + "\n" + "µCents mined: " + current_haul + str_cashout + "\n" + "Total µCents mined this session: " + total_haul + "\n"
		outstring += "Hole Familiarity Bonus: " + str(self.mine_bonus) + "%"
		return outstring  

	async def update_msg(self):
		self.update_queued = True
		await asyncio.sleep(1)
		await self.client.edit_message(self.msg, "```" + self.print_state() + "```")
		self.update_queued = False