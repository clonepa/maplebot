import re
import os
import asyncio
from binascii import b2a_hex
import logging


SYNTAX_REGEX = re.compile(r'^bot_talk_(req|res)#([0-9a-f]{30})#(.*)$')


async def get_request(client, message):
    if not message.channel.is_private:
        return

    # TODO: CHECK IF SENDER IS BOT

    parsed_message = SYNTAX_REGEX.match(message.content)
    if (not parsed_message) or parsed_message.group(1) != 'req':
        return None
    snowflake = parsed_message.group(2)
    eval_code = parsed_message.group(3)

    return (snowflake, eval_code)


async def respond_request(client, requester, snowflake, result):
    if isinstance(result, Exception):
        response_message = 'bot_talk_err#{0}#{1}::{2}'.format(snowflake, type(result).__name__, str(result))
    if isinstance(result, str):
        result = "'{0}'".format(result)
    response_message = 'bot_talk_res#{0}#{1}'.format(snowflake, str(result))
    await client.send_message(requester, response_message)
    return True


async def make_request(client, recipient_id, code, timeout=30):
    snowflake = b2a_hex(os.urandom(15)).decode('utf-8')
    request_message = 'bot_talk_req#{0}#{1}'.format(snowflake, code)
    recipient = await client.get_user_info(recipient_id)
    if not recipient:
        raise Exception('invalid recipient for request')
    request_message = await client.send_message(recipient, request_message)

    def response_check(message):
        parsed_message = SYNTAX_REGEX.match(message.content)
        if (not parsed_message):
            return False
        elif parsed_message.group(1) in ('res', 'err'):
            return True
        else:
            return False

    response = await client.wait_for_message(channel=request_message.channel,
                                             author=recipient,
                                             check=response_check,
                                             timeout=timeout)
    if response:
        parsed_response = SYNTAX_REGEX.match(response.content)
        if parsed_response.group(1) == 'res':
            logging.info('got successful response for snowflake {0}: {1}'
                         .format(parsed_response.group(2), parsed_response.group(3)))
            return eval(parsed_response.group(3))
        else:
            raise parsed_response.group(3)
    else:
        timeout_message = 'bot_talk_err#{0}#TimeOut::{1}'.format(snowflake, timeout)
        await client.send_message(recipient, timeout_message)
        return
