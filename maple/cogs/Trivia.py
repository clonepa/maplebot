import requests
import random
import logging
import time
import asyncio
from urllib.parse import unquote

from discord.ext import commands

from maple import util


logger = logging.getLogger('maple.cogs.Trivia')


def letter_to_emoji(letter):
    letter = letter.upper()
    ascii_offset = ord(letter) - 65
    if not 0 <= ascii_offset <= 25:
        raise ValueError('{} is not a letter of the alphabet'.format(letter))
    code_point = 127462 + ascii_offset
    return chr(code_point)


def format_answers(question, key=lambda x: x):
    outstr = ""
    for n, answer in enumerate(question.answers):
        letter = key(chr(65 + n))
        outstr += "\n**{}** {}".format(letter, answer)
    return outstr


class TriviaQuestion:
    def __init__(self, *, difficulty=None, question_type=None, category=None, token=None):
        if question_type is not None and question_type not in ('multiple', 'boolean'):
            raise ValueError('TriviaQuestion type must be `multiple` or `boolean`')
        if difficulty is not None and difficulty not in ('any', 'easy', 'medium', 'hard'):
            raise ValueError('TriviaQuestion difficulty must be one of `any`, `easy`, `medium`, `hard`')
        if difficulty == 'any':
            difficulty = None
        params = {'amount': 1,
                  'difficulty': difficulty,
                  'type': question_type,
                  'category': category,
                  'encode': 'url3986',
                  'token': token}
        response = requests.get('https://opentdb.com/api.php', params)
        if response.json()['response_code'] is not 0:
            raise requests.HTTPError(response.json()['response_code'])
        resobj = response.json()['results'][0]

        self.type = resobj['type']
        self.difficulty = resobj['difficulty']

        self.category = unquote(resobj['category'])
        self.question = unquote(resobj['question'])

        if self.type == 'multiple':
            answers = [unquote(ans) for ans in resobj['incorrect_answers']]
            random.shuffle(answers)
            correct_index = random.randint(0, len(answers) - 1)
            answers.insert(correct_index, unquote(resobj['correct_answer']))
        elif self.type == 'boolean':
            answers = ['True', 'False']
            correct_index = answers.index(resobj['correct_answer'])
        self.answers = answers
        self._correct = correct_index
        self._chosen = None

    @property
    def state(self):
        if self._chosen is None:
            return None
        return self._chosen == self._correct

    def answer(self, ans):
        if self.state is not None:
            raise Exception('question was already answered')
        if not -1 < ans < len(self.answers):
            raise IndexError('answer index out of range')
        self._chosen = ans
        return (self.state, self._correct)


class TriviaMessage(TriviaQuestion):

    def __init__(self, bot, user, msg, **kwargs):
        self.bot = bot
        self._initargs = kwargs
        self.msg = msg
        self.user = user
        self._msg_state = "waiting"
        super().__init__(**kwargs)
        self._msg_state = "answering"
        self.cmd_reactions_add = {}
        self.cmd_reactions_remove = {}

    async def init_msg(self):
        for i in range(len(self.answers)):
            asyncio.sleep(0.5)
            emoji = chr(127462 + i)
            self.cmd_reactions_add[emoji] = self.react_answer
        await self.update_msg(refresh_reactions=True)
        return self

    async def parse_reaction_add(self, reaction, user):
        print('hell')
        valid = False
        if user.id == self.user.id:
            print('tits')
            valid = self.cmd_reactions_add[reaction.emoji](user.id, reaction.emoji)
        else:
            print(user.id, self.user.id, user.id == self.user.id)
        return valid

    async def parse_reaction_remove(self, reaction, user):
        print(reaction.emoji.encode("unicode_escape"), user.id)
        valid = False
        if user == self.user:
            valid = self.cmd_reactions_remove[reaction.emoji](user.id, reaction.emoji)
        return valid

    def react_answer(self, user_id, emoji):
        answer = ord(emoji) - 127462
        self.answer(answer)
        self.cmd_reactions_add = {'🔁': self.new_question}
        asyncio.ensure_future(self.update_msg(refresh_reactions=True))
        self._msg_state = "waiting"

    def new_question(self, *_):
        self.cmd_reactions_add = {}
        super().__init__(**self._initargs)
        asyncio.ensure_future(self.init_msg())

    @property
    def printed(self):
        printed = ("{0.mention} here's your question:\n" +
                   "category: *{1.category}* ({1.difficulty})\n" +
                   "***{1.question}***").format(self.user, self)
        if self.state is None:
            printed += format_answers(self, letter_to_emoji)
            printed += '\nWaiting for answer...'
        else:
            answer_lines = format_answers(self, letter_to_emoji).splitlines()
            answer_lines[self._chosen + 1] += " 👈"
            answer_lines[self._correct + 1] += " ✅"
            printed += '\n' + '\n'.join(answer_lines)

        return printed

    async def update_msg(self, refresh_reactions=False):
        await self.bot.edit_message(self.msg, self.printed)
        if refresh_reactions:
            await self.bot.clear_reactions(self.msg)
            emojis_to_add = sorted(set((*self.cmd_reactions_add.keys(), *self.cmd_reactions_remove.keys())))
            print(*emojis_to_add)
            for emoji in emojis_to_add:
                await asyncio.sleep(0.25)
                await self.bot.add_reaction(self.msg, emoji)
                reac = await self.bot.wait_for_reaction(emoji, user=self.bot.user, message=self.msg)
                print(reac)


class MapleTrivia:
    def __init__(self, bot):
        self.bot = bot
        self._oqtdb_session_token = None
        self._token_timestamp = 0
        self.reactables = []

    def _get_otdb_token(self, force=False):
        if (time.time() - self._token_timestamp > (60 * 60 * 6) or
            self._oqtdb_session_token is None or
            force):
            res = requests.get('https://opentdb.com/api_token.php?command=request')
            res = res.json()
            if res['response_code'] is not 0:
                raise Exception('non-zero return code getting otdb token')
            self._otdb_session_token = res['token']
            self._token_timestamp = time.time()
        return self._otdb_session_token

    @commands.command(aliases=['trivia'], pass_context=True)
    async def mapletrivia(self, context, difficulty=None, category_id=None):
        await self.bot.type()
        msg = await self.bot.say('```...```')

        instance = TriviaMessage(self.bot, context.message.author, msg,
                                 difficulty=difficulty, category=category_id)
        self.reactables.append(instance)
        asyncio.ensure_future(instance.init_msg())

    @commands.command(aliases=['triviacats'])
    async def triviacategories(self):
        response = requests.get('https://opentdb.com/api_category.php')
        categories = response.json()['trivia_categories']

        half_len = -(-len(categories) // 2)
        split = (categories[:half_len], categories[half_len:])

        out_lines = ['[{id}] {name}'.format(**cat) for cat in split[0]]

        max_len = len(max(out_lines, key=len))

        for i, cat in enumerate(split[1]):
            out_line = '[{id}] {name}'.format(**cat)
            out_lines[i] = "{0:<{1}} {2}".format(out_lines[i], max_len, out_line)

        out_msg = util.codeblock('\n'.join(out_lines))

        await self.bot.say(out_msg)

    async def on_reaction_add(self, reaction, user):
        print('on_reaction_add', self.reactables)
        if user == self.bot.user:
            return
        for sweetbaby in self.reactables:
            print(sweetbaby)
            if sweetbaby.msg and (sweetbaby.msg.id == reaction.message.id):
                print('sweet baby...', user.id)
                await sweetbaby.parse_reaction_add(reaction, user)


def setup(bot):
    bot.add_cog(MapleTrivia(bot))
