import logging
import hashlib

from . import util

logger = logging.getLogger('maple.mtg.util')


def make_deck_hash(mainboard, sideboard=[]):
    """Makes the Cockatrice deck hash for a deck.
    I expect that there are edge cases which have not been satisfied.
    mainboard -- The list of card names, as strings. Probably fails with
        unicode names (for AE just use "AE" instead of that unicode thing --
        that's what Cockatrice does).  There shouldn't be numbers of cards; if
        you want 10 Islands then have ["Island", "Island", ..., "Island"].
    sideboard -- Same as mainboard, except containing the cards in the
        sideboard.
    """

    # Combine the 'boards. Sideboard cards are prefixed with "SB:". Card names
    # are lowercased, but not "SB:".
    cards = [
        i.lower()
        for i
        in mainboard
    ] + [
        "SB:" + i.lower()
        for i
        in sideboard
    ]

    cards.sort()

    card_hash = hashlib.sha1(";".join(cards).encode("utf-8")).digest()

    card_hash = ((ord(chr(card_hash[0])) << 32)
                + (ord(chr(card_hash[1])) << 24)
                + (ord(chr(card_hash[2])) << 16)
                + (ord(chr(card_hash[3])) <<  8)
                + (ord(chr(card_hash[4]))      ))

    # Convert to... base 32?
    card_hash = util.int2str(card_hash, 32)

    # Pad with 0s to length 8.
    card_hash = (8 - len(card_hash)) * "0" + card_hash

    return card_hash


def convert_deck_to_boards(deck_string):
    """Converts a deck in the format
        40 Storm Crow
        20 Island
        SB: 15 Storm Crow
    to a tuple of lists of the boards, for use in `make_deck_hash`.
    """

    cards = deck_string.strip().split("\n")
    boards = {
        "main": [],
        "side": [],
    }
    for i in cards:
        if not i:
            break

        target_board = "main"
        if i.startswith("SB: "):
            target_board = "side"
            i = i[len("SB: "):]

        i = i.split(" ")
        count = int(i[0])
        name = " ".join(i[1:])

        for j in range(count):
            boards[target_board].append(name)
    return boards["main"], boards["side"]


example_deck = """
4 AEtherling
48 Island
4 Jace, Architect of Thought
4 Dissolve
SB: 4 Essence Scatter
"""

# Prints 3ldd9du8, which is correct.
# print(make_deck_hash(*convert_deck_to_boards(example_deck)))
