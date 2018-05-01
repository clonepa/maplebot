import requests
import random
import logging
import time
from urllib.parse import unquote

from discord.ext import commands


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
            raise Exception('Non-zero response code in request to opentdb. Code: {}'.format(response['response_code']))
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


def format_answers(question):
    outstr = ""
    for n, answer in enumerate(question.answers):
        letter = chr(65 + n)
        outstr += "\n**{}**: {}".format(letter, answer)
    return outstr


class MapleTrivia:
    def __init__(self, bot):
        self.bot = bot
        self._otdb_session_token = None
        self._token_timestamp = 0

    def _get_otdb_token(self, force=False):
        if (time.time() - self._token_timestamp > (60 * 60 * 6) or
            _oqtdb_session_token is None or
            force):
            res = requests.get('https://opentdb.com/api_token.php?command=request')
            res = res.json()
            if res['response_code'] is not 0:
                raise Exception('non-zero return code getting otdb token')
            self._otdb_session_token = res['token']
            self._token_timestamp = time.time()
        return self._otdb_session_token

    @commands.command(aliases=['trivia'], pass_context=True)
    async def mapletrivia(self, context, difficulty=None):

        def answer_check(message):
            return message.content.lower().startswith(('answer', '!answer', 'guess', '!guess'))

        await self.bot.type()
        question = TriviaQuestion(difficulty, token=self._get_otdb_token)
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

    @commands.command()
    async def triviacategories(self):
        response = 



def setup(bot):
    bot.add_cog(MapleTrivia(bot))
