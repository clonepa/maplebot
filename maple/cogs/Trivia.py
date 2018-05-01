import requests
import random
import logging
import time
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


class TriviaQuestion:
    def __init__(self, difficulty=None, question_type=None, category=None, token=None):
        if question_type is not None and question_type not in ('multiple', 'boolean'):
            raise ValueError('TriviaQuestion type must be `multiple` or `boolean`')
        if difficulty is not None and difficulty not in ('easy', 'medium', 'hard'):
            raise ValueError('TriviaQuestion difficulty must be one of `easy`, `medium`, `hard`')
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
        self.state = None

    def answer(self, ans):
        if self.state is not None:
            raise Exception('question was already answered')
        if not -1 < ans < len(self.answers):
            raise IndexError('answer index out of range')
        elif ans == self._correct:
            self.state = True
        else:
            self.state = False
        return (self.state, self._correct)


class TriviaMessage(TriviaQuestion):

    def __init__(self, bot, msg, user, *args):
        self.bot = bot
        self.msg = msg
        self.user = user
        super(TriviaMessage, self).__init__(self, *args)

    async def parse_reaction_add(self, reaction, user):
        print(reaction.emoji.encode("unicode_escape"), user.id)
        valid = False
        if user.id == self.user:
            valid = self.cmd_reactions_add[reaction.emoji](user.id, reaction.emoji)

        if valid:
            pass

    async def parse_reaction_remove(self, reaction, user):
        print(reaction.emoji.encode("unicode_escape"), user.id)
        valid = False
        if user.id == self.user:
            valid = self.cmd_reactions_remove[reaction.emoji](user.id, reaction.emoji)

        if valid:
            pass

    async def set_reactions(self, reactions_add=None, reactions_remove=None):
        await self.bot.clear_reactions(self.msg)
        self.cmd_reactions_add = reactions_add
        self.cmd_reactions_remove = reactions_remove
        emojis_to_add = set((*reactions_add.keys(), *reactions_remove.keys()))
        for emoji in emojis_to_add:
            await self.bot.add_reaction(self.msg, emoji)

    def react_answer(self, user_id, emoji):
        answer = ord(emoji) - 127462
        self.answer(answer)
        self.print_correct()

    def print_correct(self):
        if self.state is None:
            raise Exception('TriviaMessage.print_correct() called before question was answered')
        content = self.msg.content
        if self.state is True:
            content += '\nYou were right! The answer was **{}**'

    async def update_msg(self):
        await self.client.edit_message(self.msg, self.print_state())


def format_answers(question):
    outstr = ""
    for n, answer in enumerate(question.answers):
        letter = chr(65 + n)
        outstr += "\n**{}**: {}".format(letter, answer)
    return outstr


class MapleTrivia:
    def __init__(self, bot):
        self.bot = bot
        self._oqtdb_session_token = None
        self._token_timestamp = 0

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

        def answer_check(message):
            return message.content.lower().startswith(('answer', '!answer', 'guess', '!guess'))

        difficulty = None if difficulty == 'any' else difficulty

        await self.bot.type()

        token = self._get_otdb_token()
        question = None
        while not question:
            try:
                question = TriviaQuestion(difficulty, token=token, category=category_id)
            except requests.HTTPError as exc:
                if exc.args[0] in (3, 4):
                    token = self._get_otdb_token(force=True)
                else:
                    raise exc

        q_reply = ("here's your question:\n" +
                   "category: *{0.category}* ({0.difficulty})\n" +
                   "***{0.question}***").format(question)
        q_reply += format_answers(question)
        await self.bot.reply(q_reply)

        answer = None
        while answer is None:
            answer_msg = await self.bot.wait_for_message(channel=context.message.channel,
                                                         author=context.message.author,
                                                         check=answer_check)
            try:
                answer = ord(answer_msg.content.split()[1].upper()) - 65
            except TypeError:
                await self.bot.reply('invalid answer! more than one character')
            except IndexError:
                await self.bot.reply('invalid answer!')
            else:
                if not 0 <= answer <= 90:
                    await self.bot.reply('invalid answer! not a letter')
                    answer = None

        try:
            was_correct, correct_index = question.answer(answer)
        except IndexError:
            await self.bot.reply('invalid answer! not an option')

        correct_answer = question.answers[correct_index]
        if was_correct:
            await self.bot.reply('you were right, the answer was **{}**!'.format(correct_answer))
        else:
            await self.bot.reply('sorry, that\'s wrong... the correct answer was {}: **{}**'
                                 .format(chr(correct_index + 65), correct_answer))

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


def setup(bot):
    bot.add_cog(MapleTrivia(bot))