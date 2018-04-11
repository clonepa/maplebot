import re
import os
import asyncio
from binascii import b2a_hex
import logging

BOTTALK_CHANNELID = '433427424290799641'
SYNTAX_REGEX = re.compile(r'^<@(\d+)> bot_talk_(req|res|err)#([0-9a-f]{30})#(.*)$')


async def get_request(client, message):
    print('checking request for ' + message.content)
    if message.channel.id != BOTTALK_CHANNELID:
        return

    parsed_message = SYNTAX_REGEX.match(message.content)
    print(parsed_message)
    if (not parsed_message) or parsed_message.group(2) != 'req':
        return None
    snowflake = parsed_message.group(3)
    eval_code = parsed_message.group(4)

    return (snowflake, eval_code)


async def respond_request(client, requester, snowflake, result):
    if isinstance(result, Exception):
        response_message = '{3} bot_talk_err#{0}#{1}::{2}'.format(snowflake, type(result).__name__, str(result),
                                                                  requester.mention)
    if isinstance(result, str):
        result = "'{0}'".format(result)
    response_message = '{2} bot_talk_res#{0}#{1}'.format(snowflake, str(result), requester.mention)
    await client.send_message(client.get_channel(BOTTALK_CHANNELID), response_message)
    return True


async def make_request(client, recipient_id, code, timeout=30):
    snowflake = b2a_hex(os.urandom(15)).decode('utf-8')
    recipient = await client.get_user_info(recipient_id)
    request_message = '{2} bot_talk_req#{0}#{1}'.format(snowflake, code, recipient.mention)
    if not recipient:
        raise Exception('invalid recipient for request')
    request_message = await client.send_message(client.get_channel(BOTTALK_CHANNELID), request_message)

    def response_check(message):
        parsed_message = SYNTAX_REGEX.match(message.content)
        if (not parsed_message):
            return False
        elif parsed_message.group(2) in ('res', 'err'):
            return True
        else:
            return False

    response = await client.wait_for_message(channel=request_message.channel,
                                             author=recipient,
                                             check=response_check,
                                             timeout=timeout)
    if response:
        parsed_response = SYNTAX_REGEX.match(response.content)
        if parsed_response.group(2) == 'res':
            logging.info('got successful response for snowflake {0}: {1}'
                         .format(parsed_response.group(3), parsed_response.group(4)))
            return eval(parsed_response.group(4))
        else:
            raise parsed_response.group(4)
    else:
        timeout_message = '{2} bot_talk_err#{0}#TimeOut::{1}'.format(snowflake, timeout, recipient.mention)
        await client.send_message(client.get_channel(BOTTALK_CHANNELID), timeout_message)
        return
