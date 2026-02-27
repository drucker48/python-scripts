from datetime import datetime, timedelta
from okta.client import Client as OktaClient
import asyncio

config = {
    'orgUrl': 'https://company_name.okta.com',
    'token': ''
}

current_time = datetime.now()
thirty_days =timedelta(days =30)
look_back_time = current_time - thirty_days
date_filter = look_back_time.strftime('%Y-%m-%dT%H:%M:%S.%fZ')

query_parameters = {'search': f'status eq "DEPROVISIONED" and lastUpdated lt "{date_filter}"'}

async def main():
    client = OktaClient(config)
    users, resp, err = await client.list_users(query_parameters)
    while True:
        for user in users:
            resp_deactivate, err = await client.deactivate_or_delete_user(user.id)
            print(f'{user.id} was deleted at this address {resp_deactivate}')
        if resp.has_next():
            users, err = await resp.next()
        else:
            break

loop = asyncio.get_event_loop()
loop.run_until_complete(main())
