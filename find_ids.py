import getpass

import requests


def get_groupe_e_ids():
    print("--- Groupe-E ID Finder ---")
    print("This script will help you find your Premise and Partner IDs.")

    email = input("Email: ")
    password = getpass.getpass("Password: ")

    token_url = (
        "https://login.my.groupe-e.ch/realms/my-groupe-e/protocol/openid-connect/token"
    )

    payload = {
        "grant_type": "password",
        "client_id": "portal",
        "username": email,
        "password": password,
        "scope": "openid email profile",
    }

    try:
        print("\nLogging in...")
        response = requests.post(token_url, data=payload)

        if response.status_code != 200:
            print(f"Error: Login failed (Status: {response.status_code})")
            print(
                "Check your credentials or verify if 'Password Grant' is enabled for this client."
            )
            return

        token_data = response.json()
        access_token = token_data.get("access_token")

        # Now we try to get the user info which might contain the partner IDs
        userinfo_url = "https://login.my.groupe-e.ch/realms/my-groupe-e/protocol/openid-connect/userinfo"
        headers = {"Authorization": f"Bearer {access_token}"}

        user_info_res = requests.get(userinfo_url, headers=headers)
        if user_info_res.status_code == 200:
            user_info = user_info_res.json()
            print("\n--- Found Information ---")
            print(f"Partner ID(s): {user_info.get('business_partner', 'Not found')}")
            print(f"Email: {user_info.get('email', 'Not found')}")
            print("\nNote: The 'Premise ID' is specific to your installation address.")
            print(
                "If it's not listed above, please use the Network Tab method described in README.md."
            )
        else:
            print(
                "Could not retrieve user info. Please use the manual method in README.md."
            )

    except requests.RequestException as e:
        print(f"An error occurred: {e}")


if __name__ == "__main__":
    get_groupe_e_ids()
