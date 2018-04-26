import requests
import asyncio
import math

# ---- type converters ---- #


def to_upper(argument):
    return argument.upper()


def to_lower(argument):
    return argument.lower()


# ---- string functions ---- #

def make_ptpb(text):
    response = requests.post('https://ptpb.pw/', data={"content": text})
    return next(i.split()[1] for i in response.text.split('\n') if i.startswith('url:'))


def split_every_n(tosplit, n: int, preserve_newline=False):
    if preserve_newline:
        out_list = []
        out_string = ''
        for line in tosplit.splitlines(True):
            if len(out_string + line) < n:
                out_string += line
            else:
                out_list.append(out_string)
                out_string = line
        out_list.append(out_string)
        return out_list
    else:
        return [tosplit[i:i + n] for i in range(0, len(tosplit), n)]


def codeblock(string):
    return '```{0}```'.format(string)


async def big_output_confirmation(context, output: str, max_len=1500, formatting=str, bot=None):
    '''checks if some output is longer than max_len(default: 1500). if so, asks user for confirmation on sending,
        if confirmed, says output with formatting given by optional function parameter 'formatting' '''
    def check(message):
        msg = message.content.lower()
        return (msg.startswith('y') or msg.startswith('n'))

    output_length = len(output)
    if output_length > max_len:
        await bot.reply("do you really want me to send all this? it's {0} characters long... [y/n]"
                        .format(output_length))
        reply = await bot.wait_for_message(channel=context.message.channel,
                                           author=context.message.author,
                                           check=check,
                                           timeout=60)
        if not reply:
            return None
        reply_content = reply.content.lower()
        confirm = True if reply_content.startswith('y') else False
        if confirm:
            processed = split_every_n(output, max_len, True)
        else:
            await bot.reply("ok!")
            return False
    else:
        processed = [output]

    for split in processed:
        await bot.say(formatting(split))
        asyncio.sleep(0.05)
    return True


def calc_elo_change(winner, loser):
    '''calculates elo change for given winner and loser values'''
    k = 32
    r1 = math.pow(10, winner / 400)
    r2 = math.pow(10, loser / 400)

    e1 = r1 / (r1 + r2)
    e2 = r2 / (r1 + r2)

    rr1 = winner + k * (1.0 - e1)
    rr2 = loser + k * (0 - e2)

    return math.ceil(rr1), math.ceil(rr2)
