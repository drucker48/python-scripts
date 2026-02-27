import asyncio
import aiohttp
import re
from urllib.parse import urlencode
import csv

# Instantiating with a Python dictionary in the constructor
config = {
    'orgUrl': 'https://findheadway.okta.com',
    'token': ''
}

def find_next_link(link_headers):
    """
    Parses a list of Link headers to find the URL for the next page.
    """
    if not link_headers:
        return None
    
    # Loop through all link headers provided
    for header in link_headers:
        # Check each header for the 'rel="next"' pattern
        match = re.search('<(.*?)>; rel="next"', header)
        if match:
            # If found, return the URL immediately
            return match.group(1)
            
    # If the loop finishes, no 'next' link was found
    return None

def parse_version(v_string):
    """Converts a version string like '15.1.0' into a tuple of ints (15, 1, 0)."""
    if not v_string:
        return (0, 0, 0)  
    try:
        # Split by '.' and convert each part to an integer
        return tuple(map(int, v_string.split('.')))
    except (ValueError, AttributeError):
        return (0, 0, 0)

async def main():
    all_devices = []

    params = {
        'limit': 200,
        'search': 'status eq "ACTIVE" and profile.platform eq "MACOS"'
    }
    query_string = urlencode(params)
    base_url = config['orgUrl'] + '/api/v1/devices'
    next_url = f"{base_url}?{query_string}"
    
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": f"SSWS {config['token']}"
    }

    async with aiohttp.ClientSession() as session:
        # Pt1 Find all devices
        while next_url:
            async with session.get(next_url, headers=headers) as response:
                if response.status != 200:
                    print(f"Error: Received status code {response.status}")
                    break
                
                current_page_devices = await response.json()
                all_devices.extend(current_page_devices)

                next_url = find_next_link(response.headers.getall("Link"))
                
                if next_url:
                    print(f"Fetching next page...")

        print("\n" + "="*30)
        print(f"✅ Success! Found a total of {len(all_devices)} SELECTED devices.")
        print("="*30)
        for device in all_devices:
            print(f"  - Device ID: {device.get('id')}, Status: {device.get('status')}")

        # Pt2 Confirm and delete
        if not all_devices:
            print("No devices to delete. Exiting.")
            return
        
        delete_list = []
        target_version = parse_version("15.0.0")
        for device in all_devices:
            device_profile = device.get('profile', {})
            os_version_tuple = parse_version(device_profile.get('osVersion'))
            if os_version_tuple < target_version:
                delete_list.append(device)

        # Export data confirmation prompt
        print("\nWould you like a csv of devices proposed to be changed?")
        confirm = input('To proceed, type "YES" and press Enter: ')

        if confirm != "YES":
            print("No CSV option selected.")
            return
        else:
            keys_list = delete_list[0].keys() if delete_list else []
            with open("to_be_deleted_devices.csv", "w", newline="") as csvfile:
                csv_writer = csv.DictWriter(csvfile, fieldnames= keys_list)
                csv_writer.writeheader()
                csv_writer.writerows(delete_list)

        # Safety Deactiavtion of devices 
        print("\nThis script will permanently deactivate the devices listed above.")
        confirm = input('To proceed, type "YES" and press Enter: ')

        if confirm != "YES":
            print("Confirmation not received. Exiting without deactivating devices.")
            return
        
        # Need to deactivate devices 
        for device in delete_list:
            device_id = device.get('id')
            deactivate_url = f"{base_url}/{device_id}/lifecycle/deactivate"

            async with session.post(deactivate_url, headers=headers) as deactivated_response:
                # A successful deletion returns a 204 No Content status
                if deactivated_response.status == 204:
                    print(f"✅ Successfully deactivated device ID: {device_id}")
                else:
                    response_text = await deactivated_response.text()
                    print(f"❌ FAILED to delete device ID: {device_id} (Status: {deactivated_response.status}, Response: {response_text})")

        # Safety confirmation prompt
        print("\nThis script will permanently delete the devices listed above.")
        confirm = input('To proceed, type "YES" and press Enter: ')

        if confirm != "YES":
            print("Confirmation not received. Exiting without deleting devices.")
            return

        print("\nStarting deletion process...")
        for device in delete_list:
            device_id = device.get('id')
            delete_url = f"{base_url}/{device_id}"
            
            async with session.delete(delete_url, headers=headers) as delete_response:
                # A successful deletion returns a 204 No Content status
                if delete_response.status == 204:
                    print(f"✅ Successfully deleted device ID: {device_id}")
                else:
                    response_text = await delete_response.text()
                    print(f"❌ FAILED to delete device ID: {device_id} (Status: {delete_response.status}, Response: {response_text})")

    
asyncio.run(main())
