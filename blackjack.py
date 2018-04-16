import discord
import asyncio
import itertools
import random

#SUITS = ('♧', '♢', '♡', '♤')
#RANKS = ('Ⅱ', 'Ⅲ', 'Ⅳ', 'Ⅴ', 'Ⅵ', 'Ⅶ', 'Ⅷ', 'Ⅸ', 'Ⅹ', 'J', 'Q', 'K', 'A')

SUITS = ('c', 'd', 'h', 's')
RANKS = ('2', '3', '4', '5', '6', '7', '8', '9', 'T', 'J', 'Q', 'K', 'A')

SCORES = {'2':2,'3':3,'4':4,'5':5,'6':6,'7':7,'8':8,'9':9,'T':10,'J':10,'Q':10,'K':10,'A':11}
 
DECK = tuple(''.join(card) for card in itertools.product(RANKS, SUITS))

def deal_hand():
    return random.sample(DECK, 2)

def eval_hand(hand):
    total = 0
    for card in hand:
        total += SCORES[card[0]]
    return total
