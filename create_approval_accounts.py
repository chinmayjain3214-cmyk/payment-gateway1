"""Interactively create/update the Department Head and Finance Officer accounts."""
from getpass import getpass

from auth import create_user


def create_role_account(role: str, label: str) -> None:
    print("\n" + label + " account (leave username blank to skip)")
    username = input("Username: ").strip()
    if not username:
        print("Skipped " + label + ".")
        return
    full_name = input("Full name: ").strip()
    password = getpass("Password: ")
    confirm = getpass("Confirm password: ")
    if password != confirm:
        print("Passwords did not match. " + label + " account was not changed.")
        return
    if len(password) < 8:
        print("Use a password with at least 8 characters. Account was not changed.")
        return
    create_user(username, full_name, role, password)
    print("Created/updated " + label + " account: " + username)


def main() -> None:
    create_role_account("department_head", "Department Head")
    create_role_account("finance_officer", "Finance Officer")
    print("\nThe existing 'approver' role remains the Final Approver account.")


if __name__ == "__main__":
    main()
