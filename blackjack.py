import discord
import asyncio
import itertools
import random
import json


#alternative symbol storage
#SUITS = ('♧', '♢', '♡', '♤')
#RANKS = ('Ⅱ', 'Ⅲ', 'Ⅳ', 'Ⅴ', 'Ⅵ', 'Ⅶ', 'Ⅷ', 'Ⅸ', 'Ⅹ', 'J', 'Q', 'K', 'A')
#SUITS = ('♣', '♦', '♥', '♠')

#under heavy construction

class BlackJackMachine:
    SUITS = ('c', 'd', 'h', 's')
    RANKS = ('2', '3', '4', '5', '6', '7', '8', '9', 'T', 'J', 'Q', 'K', 'A')
    
    #smarter ways to do this, maybe later
    SCORES = {'2':2,'3':3,'4':4,'5':5,'6':6,'7':7,'8':8,'9':9,'T':10,'J':10,'Q':10,'K':10,'A':11}
    DECK = tuple(''.join(card) for card in itertools.product(RANKS, SUITS))
    
    def __init__(self, client):
        self.msg = None
        self.active_players = {}
        self.dealer_hand = {}
        self.dealer_last_hand = 0
        self.dealer_result = ""
        self.dealer_previous_result = ""
        self.card_shoe = list(self.DECK)
        self.refill_shoe(4)     
        self.current_state = "bet"
        self.client = client
        self.cmd_reactions_add = {'\U0001f60e': self.cmd_join,
                                  '\U0001f1ed': self.cmd_hit,
                                  '\U0001f1f8': self.cmd_stand,
                                  '\u2935': self.cmd_double_down,
                                  #'\U0001f4b8': self.cmd_insurance_bet, #not sure if we want insurance bets yet...
                                  '\U0001f198': self.cmd_surrender,
                                  '\u25b6': self.cmd_inc_bet_small,
                                  '\u23e9': self.cmd_inc_bet_medium,
                                  '\u23ed': self.cmd_inc_bet_large,
                                  '\U0001f196': self.cmd_clear_bet,
                                  '\U0001f171': self.cmd_accept_bet}
        self.cmd_reactions_remove = {'\U0001f60e': self.cmd_leave}
                                     
            
    def refill_shoe(self, decks = 4):
        self.card_shoe = list(self.DECK) * decks
        random.shuffle(self.card_shoe)

    def draw_cards(self, amount=2):
        #todo: check if shoe is almost empty and refill it
        outlist = []
        for i in range(amount):
            outlist += [self.card_shoe.pop()]
        return outlist

    def eval_state(self):
        if self.current_state == "bet":
            #check if all bets are accpeted
            all_ready = True
            for i in self.active_players:
                if self.active_players[i]['playstate'] != 'bet_locked' and self.active_players[i]['playstate'] != 'waiting':
                    all_ready = False
            if all_ready:
                for i in self.active_players:
                    if self.active_players[i]['playstate'] == 'bet_locked':
                        self.active_players[i]['hand'] = self.draw_cards()
                        self.active_players[i]['playstate'] = 'action'
                self.current_state = "player_action"
                self.dealer_hand = self.draw_cards()
                if self.score_hand(self.dealer_hand) == 21:
                    self.current_state = "dealer_action"
                self.eval_state()
        elif self.current_state == "player_action":
            #todo: dealer peek
            #check if all players have stood or lost
            all_ready = True
            for p in self.active_players:
                if self.active_players[p]['playstate'] == 'action':
                    all_ready = False
            if all_ready:
                self.current_state = "dealer_action"
                self.eval_state()
        elif self.current_state == "dealer_action":
            asyncio.ensure_future(self.dealer_action())
            #self.reset()
            

    async def dealer_action(self):

        #todo: find highest player hand and stop when we beat it
        while self.score_hand(self.dealer_hand) < 17:
            self.dealer_hand += [self.card_shoe.pop()]
            await self.update_msg()
            await asyncio.sleep(1.25)
            
        #todo: set result for dealer/players to win/lose/push

        await asyncio.sleep(2)
        
        self.reset()
        await self.update_msg()

    async def parse_reaction_remove(self, reaction, user):
        pass
        #todo: allow user to exit game. if current state is action, auto surrender
        
    async def parse_reaction_add(self, reaction, user):
        print(reaction.emoji.encode("unicode_escape"), user.id)
        if reaction.emoji in self.cmd_reactions_add:
            self.cmd_reactions_add[reaction.emoji](user.id)
            
        #keep join emoji
        if reaction.emoji != "\U0001f60e":
            await self.client.remove_reaction(self.msg, reaction.emoji, user)       

        self.eval_state()    
        await self.update_msg()
            
        # \U0001f60e - sunglasses
        # \U0001f1ed - H
        # \U0001f1f8 - S
        # \U0001f198 - SOS
        # \U000u23ea - rewind fast
        # \U000u25c0 - rewind
        # \U000u25b6 - forward
        # \U000u23e9 - fast forward
        # \U0001f196 - NG
        # \U0001f171 - B
        
    def reset(self):
        for i in self.active_players:
                self.active_players[i]['playstate'] = 'betting'
                self.active_players[i]['previous_result'] = self.active_players[i]['current_result']
                self.active_players[i]['current_result'] = ""
                self.active_players[i]['last_hand'] = self.score_hand(self.active_players[i]['hand'])
                self.active_players[i]['hand'] = {}
        self.dealer_hand = {}
        self.current_state = "bet"
        
    #input
    def cmd_join(self, user):
        self.active_players[user] = {'current_bet': 0,
                                     'hand': {},
                                     'last_hand': 0,                                 
                                     'playstate': 'waiting',
                                     'last_payout': 0,
                                     'previous_result': "",
                                     'current_result': ""}
        
        if self.current_state == 'bet':
            self.active_players[user]['playstate'] = 'betting'
        print (self.active_players)

        
    def cmd_leave(self, user):
        self.active_players.pop(user)

        
    def cmd_hit(self, user):
        if self.current_state != "player_action" or self.active_players[user]['playstate'] != 'action':
            return
        self.active_players[user]['hand'] += [self.card_shoe.pop()]
        pscore = self.score_hand(self.active_players[user]['hand'])
        if pscore > 21:
            self.active_players[user]['playstate'] = 'bust'
        elif pscore == 21:
            self.active_players[user]['playstate'] = 'stand'

    def cmd_double_down(self, user):
        if self.current_state != "player_action" or self.active_players[user]['playstate'] != 'action':
            return
        pass
        #todo: implement this
    
    def cmd_insurance_bet(self, user):
        if self.current_state != "player_action" or self.active_players[user]['playstate'] != 'action':
            return
        pass
        #todo: implement this, maybe...
    
    def cmd_stand(self, user):
        if self.current_state != "player_action" or self.active_players[user]['playstate'] != 'action':
            return
        self.active_players[user]['playstate'] = 'stand'

        
    def cmd_surrender(self, user):
        if self.current_state != "player_action" or self.active_players[user]['playstate'] != 'action':
            return
        self.active_players[user]['playstate'] = 'surrender'
        self.eval_state()
        
    def cmd_inc_bet_small(self, user):
        if self.current_state != "bet" or self.active_players[user]['playstate'] != 'betting':
            return
        
        self.active_players[user]['current_bet'] += 1
            
        self.eval_state()
        
    def cmd_inc_bet_medium(self, user):
        if self.current_state != "bet" or self.active_players[user]['playstate'] != 'betting':
            return
        
        self.active_players[user]['current_bet'] += 10
            


    def cmd_inc_bet_large(self, user):
        if self.current_state != "bet" or self.active_players[user]['playstate'] != 'betting':
            return
        
        self.active_players[user]['current_bet'] += 25
            

       
    def cmd_dec_bet_small(self, user):
        if self.current_state != "bet" or self.active_players[user]['playstate'] != 'betting':
            return
        if self.active_players[user]['current_bet'] > 1:
            self.active_players[user]['current_bet'] -= 1

        
    def cmd_dec_bet_large(self, user):
        if self.current_state != "bet" or self.active_players[user]['playstate'] != 'betting':
            return
        if self.active_players[user]['current_bet'] > 10:
            self.active_players[user]['current_bet'] -= 10

        
    def cmd_clear_bet(self, user):
        if self.current_state != "bet" or self.active_players[user]['playstate'] != 'betting':
            return
        self.active_players[user]['current_bet'] = 0
        
    def cmd_accept_bet(self, user):
        if self.current_state != "bet" or self.active_players[user]['playstate'] != 'betting':
            return
        self.active_players[user]['playstate'] = 'bet_locked'


    def score_hand(self, hand):
        total = 0
        if hand == {} or hand == None:
            return 0
        num_aces = 0
        for card in hand:
            total += self.SCORES[card[0]]
            if card[0] == 'A':
                num_aces += 1
        while num_aces > 0:
            if total > 21:
                total -= 10
                num_aces -= 1
            else:
                break
            
        return total

    def print_state(self):
        #todo: make this print pretty
        lines = []
        lines += ["DEALER HAND: {0} ({1})".format(self.dealer_hand, self.score_hand(self.dealer_hand))]
        for pp in self.active_players:
            lines += ['{0} HAND: {1} ({2}), BET: {3}, PREVIOUS HAND: {4}, STATE: {5}'.format(pp[:8], self.active_players[pp]['hand'], self.score_hand(self.active_players[pp]['hand']), self.active_players[pp]['current_bet'], self.active_players[pp]['last_hand'], self.active_players[pp]['playstate'])]
                                                                                                            

        output = ""
        for l in lines:
            output += l + "\n"
        return output
    
    async def update_msg(self):
        await self.client.edit_message(self.msg, self.print_state())
    
