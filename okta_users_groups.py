from datetime import datetime, timedelta
from okta.client import Client as OktaClient
import asyncio
import csv


config = {
    'orgUrl': 'https://findheadway.okta.com',
    'token': ''
}

current_time = datetime.now()
thirty_days =timedelta(days =30)
look_back_time = current_time - thirty_days
date_filter = look_back_time.strftime('%Y-%m-%dT%H:%M:%S.%fZ')

# status eq "DEPROVISIONED" and lastUpdated lt “date-30 days”
query_parameters = {'search': f'status eq "DEPROVISIONED" and lastUpdated lt "{date_filter}"'}


target_list = []
group_list = []
async def main():
    client = OktaClient(config)
    users, resp, err = await client.list_users(query_parameters)
    while True:
        for user in users:
            user_groups, _, err_groups = await client.list_user_groups(user.id)
            if err_groups:
                print(f"Could not fetch groups for {user.profile.login}: {err_groups}")
                groups_str = "Error fetching groups"
            elif user_groups:
                groups_list = [group.profile.name for group in user_groups]
                groups_str = ", ".join(groups_list)
            else:
                groups_str = 'No Groups'

            print(user.id, user.profile.login, user.last_updated, groups_str) 
            target_list.append([user.id, user.profile.login, user.last_updated, groups_str])
        if resp.has_next():
            users, err = await resp.next()
        else:
            break

loop = asyncio.get_event_loop()
loop.run_until_complete(main())


print(len(target_list))


csv_filename = 'okta_deprovisioned_users.csv'
with open(csv_filename, 'w', newline='', encoding='utf-8') as csvfile:
    # Create a csv writer object
    csv_writer = csv.writer(csvfile)

    # Write the header row
    csv_writer.writerow(['Email', 'Last Updated'])

    # Write all the user data from the list
    csv_writer.writerows(target_list)
