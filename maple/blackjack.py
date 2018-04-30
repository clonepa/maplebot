import discord
import asyncio
import itertools
import random
import json
import math
import maple.brains

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
        self.dealer_status = ""
        self.card_shoe = list(self.DECK)
        self.refill_shoe(4)     
        self.current_state = "bet"
        self.client = client
        self.cmd_reactions_add = {'\U0001f60e': self.cmd_join,
                                  '\U0001f1ed': self.cmd_hit,
                                  '\U0001f1f8': self.cmd_stand,                                 
                                  #'\U0001f4b8': self.cmd_insurance_bet, #not sure if we want insurance bets yet...
                                  '\U0001f198': self.cmd_surrender,
                                  '\u2935': self.cmd_double_down,
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
        if len(self.card_shoe) < 26:
            self.refill_shoe(4)
        outlist = []
        for i in range(amount):
            outlist += [self.card_shoe.pop()]
        return outlist

    def eval_state(self):
        if self.current_state == "bet":
            #check if all bets are accpeted
            all_ready = True
            for i in self.active_players:
                if self.active_players[i]['playstate'] != 'bet locked' and self.active_players[i]['playstate'] != 'waiting':
                    all_ready = False
            if all_ready:
                for i in self.active_players:
                    if self.active_players[i]['playstate'] == 'bet locked':
                        self.active_players[i]['hand'] = self.draw_cards()
                        if self.score_hand(self.active_players[i]['hand']) == 21:
                            self.active_players[i]['playstate'] = 'stand'
                        else:
                            self.active_players[i]['playstate'] = 'action'
                self.current_state = "player_action"
                self.dealer_hand = self.draw_cards()
                #dealer peek
                if self.score_hand(self.dealer_hand) == 21:
                    self.current_state = "dealer_action"
                self.eval_state()
        elif self.current_state == "player_action":
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
        
        #find highest player hand and stop when we beat it or hit 17
        highest_player_score = 0
        for p in self.active_players:
            pstate = self.active_players[p]['playstate']
            if pstate == 'surrender' or pstate == 'bust':
                continue
            current_player_score = self.score_hand(self.active_players[p]['hand'])
            if current_player_score == 21 and len(self.active_players[p]['hand']) == 2:
                continue
            
            if current_player_score > highest_player_score:
                highest_player_score = current_player_score

        await self.update_msg()
        await asyncio.sleep(1.25)
        while self.score_hand(self.dealer_hand) < min(highest_player_score, 17):
            self.dealer_hand += [self.card_shoe.pop()]
            await self.update_msg()
            await asyncio.sleep(1.25)

        if self.score_hand(self.dealer_hand) > 21:
            self.dealer_status = "BUST"
           
        #set result for dealer/players to win/lose/push
        self.figure_out_who_won()
        self.settle_bets()
        await self.update_msg()
        
        await asyncio.sleep(3)
        
        self.reset()
        await self.update_msg()
        
    def figure_out_who_won(self):
        
        for p in self.active_players:
            pp = self.active_players[p]
            is_natural = (len(pp['hand']) == 2 and self.score_hand(pp['hand']) == 21)
            
            if pp['playstate'] == 'surrender':
                pp['current_result'] = "SURRENDER"
                continue

            if is_natural and self.score_hand(self.dealer_hand) == 21 and len(self.dealer_hand) > 2:
                pp['current_result'] = "WIN"
            
            if self.score_hand(self.dealer_hand) > 21:
                if pp['playstate'] == 'bust':
                    pp['current_result'] = "PUSH"
                else:
                    pp['current_result'] = "WIN"
                continue
            
            if pp['playstate'] == 'bust':
                pp['current_result'] = "LOSE"
            
            elif self.score_hand(pp['hand']) > self.score_hand(self.dealer_hand):
                pp['current_result'] = "WIN"
            elif self.score_hand(pp['hand']) == self.score_hand(self.dealer_hand):
                pp['current_result'] = "PUSH"
            else:
                pp['current_result'] = "LOSE"

    def settle_bets(self):
        #todo: implement 3:2 for blackjack
        for p in self.active_players:
            pp = self.active_players[p]
            bet = pp["current_bet"]
            if pp['current_result'] == "WIN":
                pp['session_winnings'] += bet
                maple.brains.adjust_cash(p, bet/100)
            elif pp['current_result'] == "LOSE":
                pp['session_winnings'] -= bet
                maple.brains.adjust_cash(p, -bet/100)
            elif pp['current_result'] == "SURRENDER":
                pp['session_winnings'] -= int(math.ceil(bet/2))
                maple.brains.adjust_cash(p, -int(math.ceil(bet/2))/100)

            if pp['current_bet']/100 > maple.brains.get_record(p)['cash']:
            	pp['current_bet'] = math.max(0, int(maple.brains.get_record(p)['cash'] * 100))
        	
        
    def print_dealer_info(self):
        outstring = ""
        strhand = ""

        if len(self.dealer_hand) == 0:
            strhand = "? ? ? ?"
        elif self.current_state == 'player_action':
            strhand = self.dealer_hand[0] + " ?? : " + str(self.SCORES[self.dealer_hand[0][0]]) 
        else:
            for h in self.dealer_hand:
                strhand += h + " "
            strhand += ": " + str(self.score_hand(self.dealer_hand))
        outstring = "DEALER: " + strhand + " " + self.dealer_status
        outstring += "  [Prev. Hand: " + str(self.dealer_last_hand) + "]"
        return outstring
    def print_player_info(self, p):
        outstring = ""
        strhand = ""
        
        if len(p['hand']) == 0:
            strhand = "?? ??"
        else:
            for h in p['hand']:
                strhand += h + " "
            strhand += ": " + str(self.score_hand(p['hand']))
        
        outstring += str(p['name']) + " (" + p['playstate'] + ")\n"
        outstring += "  " + strhand + " " + p['current_result'] + "\n"
        #outstring += "  [Prev. Hand: " + str(p['last_hand']) + " " + p['previous_result'] + "]"
        outstring += "  [Bet: " + str(p['current_bet']) + "] [Session Winnings: " + str(p['session_winnings']) + "] [Prev. Hand: " + str(p['last_hand']) + " " + p['previous_result'] + "]"
        
        return outstring
        
        
    async def parse_reaction_remove(self, reaction, user):
        valid = False
        if reaction.emoji in self.cmd_reactions_remove:
            valid = self.cmd_reactions_remove[reaction.emoji](user.id)
        if valid:
            self.eval_state()
            await self.update_msg()
            
    async def parse_reaction_add(self, reaction, user):
        print(reaction.emoji.encode("unicode_escape"), user.id)
        valid = False
        if reaction.emoji in self.cmd_reactions_add and (reaction.emoji == "\U0001f60e" or user.id in self.active_players):
            valid = self.cmd_reactions_add[reaction.emoji](user.id)
            
        #keep join emoji
        if reaction.emoji != "\U0001f60e":
            await self.client.remove_reaction(self.msg, reaction.emoji, user)       

        if valid:
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
                self.active_players[i]['previous_result'] = self.active_players[i]['current_result'][:1]
                self.active_players[i]['current_result'] = ""
                self.active_players[i]['last_hand'] = self.score_hand(self.active_players[i]['hand'])
                self.active_players[i]['hand'] = {}
                if self.active_players[i]['double_down']:
                    self.active_players[i]['current_bet'] = int(self.active_players[i]['current_bet'] / 2)
                    self.active_players[i]['double_down'] = False
        self.dealer_last_hand = self.score_hand(self.dealer_hand)
        self.dealer_hand = {}
        self.dealer_status = ""
        self.current_state = "bet"
        
    #input
    def cmd_join(self, user):
        user_rec = maple.brains.get_record(user)
        print(user_rec)
        self.active_players[user] = {'name': user_rec['name'],
                                     'current_bet': 0,
                                     'hand': {},
                                     'last_hand': 0,                                 
                                     'playstate': 'waiting',
                                     'session_winnings': 0,
                                     'previous_result': "",
                                     'current_result': "",
                                     'double_down': False}
        
        if self.current_state == 'bet':
            self.active_players[user]['playstate'] = 'betting'
        print (self.active_players)
        return True
        
    def cmd_leave(self, user):
        #todo: auto surrender
        if user in self.active_players:
        	if self.current_state != 'bet':
        		maple.brains.adjust_cash(user, -self.active_players[user]['current_bet']/100)
        	elif self.current_state == 'player_action' and len(sself.active_players[user]['hand'] == 2):
        		maple.brains.adjust_cash(user, -(self.active_players[user]['current_bet']/2)/100)
        	self.active_players.pop(user)
        	return True
        
    def cmd_hit(self, user):
        if self.current_state != "player_action" or self.active_players[user]['playstate'] != 'action':
            return False
        self.active_players[user]['hand'] += [self.card_shoe.pop()]
        pscore = self.score_hand(self.active_players[user]['hand'])
        if pscore > 21:
            self.active_players[user]['playstate'] = 'bust'
        elif pscore == 21:
            self.active_players[user]['playstate'] = 'stand'
        return True
        
    def cmd_double_down(self, user):
        if self.current_state != "player_action" or self.active_players[user]['playstate'] != 'action':
            return False
        self.active_players[user]['current_bet'] += self.active_players[user]['current_bet'] 
        self.active_players[user]['hand'] += [self.card_shoe.pop()]
        if self.score_hand(self.active_players[user]['hand']) > 21:
            self.active_players[user]['playstate'] = 'bust'
        else:
            self.active_players[user]['playstate'] = 'stand'
        self.active_players[user]['double_down'] = True
        return True
        
    def cmd_insurance_bet(self, user):
        if self.current_state != "player_action" or self.active_players[user]['playstate'] != 'action':
            return False
        pass
        #todo: implement this, maybe...
    
    def cmd_stand(self, user):
        if self.current_state != "player_action" or self.active_players[user]['playstate'] != 'action':
            return False
        self.active_players[user]['playstate'] = 'stand'
        return True
        
    def cmd_surrender(self, user):
        if self.current_state != "player_action" or self.active_players[user]['playstate'] != 'action':
            return False
        if len(self.active_players[user]['hand']) > 2:
            return False
        self.active_players[user]['playstate'] = 'surrender'
        return True
        
    def cmd_inc_bet_small(self, user):
        if self.current_state != "bet" or self.active_players[user]['playstate'] != 'betting':
            return False
        
        self.active_players[user]['current_bet'] += 10
        if self.active_players[user]['current_bet']/100 > maple.brains.get_record(user)['cash']:
        	self.active_players[user]['current_bet'] = int(maple.brains.get_record(user)['cash'] * 100)
        return True 
        
    def cmd_inc_bet_medium(self, user):
        if self.current_state != "bet" or self.active_players[user]['playstate'] != 'betting':
            return False
        
        self.active_players[user]['current_bet'] += 50
        if self.active_players[user]['current_bet']/100 > maple.brains.get_record(user)['cash']:
        	self.active_players[user]['current_bet'] = int(maple.brains.get_record(user)['cash'] * 100)

        return True

    def cmd_inc_bet_large(self, user):
        if self.current_state != "bet" or self.active_players[user]['playstate'] != 'betting':
            return False
        
        self.active_players[user]['current_bet'] += 200
        if self.active_players[user]['current_bet']/100 > maple.brains.get_record(user)['cash']:
        	self.active_players[user]['current_bet'] = int(maple.brains.get_record(user)['cash'] * 100)

        return True
       
    def cmd_dec_bet_small(self, user):
        if self.current_state != "bet" or self.active_players[user]['playstate'] != 'betting':
            return False
        if self.active_players[user]['current_bet'] > 1:
            self.active_players[user]['current_bet'] -= 1
        return True
        
    def cmd_dec_bet_large(self, user):
        if self.current_state != "bet" or self.active_players[user]['playstate'] != 'betting':
            return False
        if self.active_players[user]['current_bet'] > 10:
            self.active_players[user]['current_bet'] -= 10
        return True
        
    def cmd_clear_bet(self, user):
        if self.current_state != "bet" or self.active_players[user]['playstate'] != 'betting':
            return False
        self.active_players[user]['current_bet'] = 0
        return True
    
    def cmd_accept_bet(self, user):
        if self.current_state != "bet" or self.active_players[user]['playstate'] != 'betting':
            return False
        self.active_players[user]['playstate'] = 'bet locked'
        return True

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
        lines = ["～ 𝓜𝓪𝓹𝓵𝓮𝓫𝓸𝓽 𝓟𝓻𝓮𝓼𝓮𝓷𝓽𝓼 𝓥𝓮𝓰𝓪𝓼-𝓢𝓽𝔂𝓵𝓮 𝓑𝓵𝓪𝓬𝓴𝓳𝓪𝓬𝓴 ～"]
        lines += [self.print_dealer_info()]
        for pp in self.active_players:
            lines += [self.print_player_info(self.active_players[pp] ) ]                                                                                              

        output = ""
        for l in lines:
            output += l + "\n"
        return "```" + output + "```"
    
    async def update_msg(self):
        await self.client.edit_message(self.msg, self.print_state())
    
