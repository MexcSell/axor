---
title: Your account and security
section: start
order: 2
icon: lock
summary: Signing in, two-factor authentication, recovery codes, passwords and sessions.
---
## Creating an account

Choose **Create account** on the sign-in screen. It works while an administrator has public registration open; if it's closed, ask an administrator to open it for you. If administrators approve new accounts, you'll see **Request sent**: sign in once an administrator has approved you (and set up your authenticator then, if two-factor is required).

- **Username:** 3 to 32 characters: lowercase letters, digits, `_`, `.` and `-`. You can sign in with it or your email.
- **Email:** optional.
- **Password:** at least 12 characters mixing three kinds (lowercase, uppercase, digits, symbols), or 16 characters or more of anything. Common passwords and passwords found in known breaches are refused. The breach check sends only the first 5 characters of the password's hash, never the password.

If your server requires two-factor, you set it up right after: see below.

## Two-factor authentication

Two-factor means every sign-in needs a 6-digit code from an authenticator app on your phone as well as your password.

1. Install an authenticator app: Google Authenticator, Microsoft Authenticator, Authy, 1Password or similar.
2. Scan the QR code AXoR shows. If you can't scan, open **Can't scan?** and type the key in.
3. Enter the code the app shows to finish.

An administrator decides whether two-factor is required for everyone (**Password + 2FA**) or optional (**Username + password**). When it's optional you can still turn it on from the account menu (**Turn on two-factor**), and once it's on you're always asked for a code.

> [!IMPORTANT]
> Codes can't be reused, and five wrong codes in a row end the sign-in attempt: you start again from your password.

## Recovery codes

When you set up two-factor you get **10 one-time recovery codes**. Each one signs you in once if you lose your phone. They're shown only once, so copy or download them and keep them somewhere safe, away from your phone.

- At sign-in, choose **Use a recovery code** and type one in.
- The account menu shows how many you have left. **New recovery codes** replaces all of them (it asks for an authenticator code).
- Lost your phone and your codes? An administrator can reset your two-factor, and you set it up again at your next sign-in.

## Passwords

- **Change password** is in the account menu. It asks for your current password and, with two-factor on, a code. Changing it signs out every other device.
- If an administrator resets your password, you get a temporary one and must choose a new password at your next sign-in.

## Sessions and devices

- A session ends after **24 hours** without activity, or after **7 days** at most.
- **Sign out of all devices** in the account menu ends every session, this one included.
- Your theme, accent color, τ / $ unit and recommendation profile are saved to your account, so they follow you to other devices.

## Why you might be blocked

| What you see | Why | What to do |
|---|---|---|
| "Incorrect username or password." | A wrong login or password. AXoR never says which, so nobody can probe for accounts. | Check both and try again. |
| "Too many failed attempts. Account locked…" | Five wrong passwords lock the account for 15 minutes. | Wait, or ask an administrator to unlock you. |
| "Too many attempts. Try again in …s." | More than 10 sign-ins from your network in 5 minutes. | Wait for the time shown. |
| "This account is disabled." | An administrator disabled it. | Contact an administrator. |
| "Sign-in expired. Enter your password again." | You waited too long at the code step. | Start again from your password. |

> [!WARNING]
> Never share your recovery codes or authenticator codes. Nobody from AXoR, administrators included, will ask you for them.
