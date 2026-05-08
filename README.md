# Discord Verification via MEXC Referral API

This folder contains an overview of the verification bot.
It explains the core flow, integration points, and the MEXC referral API call without exposing the full source.

## What this bot does

- Accepts a Discord user's MEXC UID through a modal form.
- Calls the MEXC affiliate/referral API to verify the UID belongs to the configured referral.
- If the UID is valid, the bot either:
  - auto-approves the verification, or
  - sends a pending review request to staff.
- Approved users receive a verified role in the server.
- The bot also supports staff review, voice interview channels, CSV exports, and admin configuration.

---

## Flow summary

1. A user clicks the verification panel button.
2. A modal prompts the user for their MEXC UID.
3. The bot checks the MEXC referral API for membership.
4. If the UID is not in the referral, verification is blocked.
5. If the UID is found, the bot assigns the verified role.
6. The user receives a DM confirmation once approved.
7. If auto-approve is disabled, the request is sent to staff.
8. Staff can approve, deny, or create a VC for interview.

---

## User experience

- `/verify` opens the MEXC UID modal.
- `/vmyinfo` shows the user's own verification details.
- If auto-approve is off, users submit to the pending channel and wait for staff review.
- If auto-approve is on, valid UIDs are immediately verified.

---

## Staff experience

- Staff review requests in the Pending channel.
- Staff can approve or deny requests with a single click.
- Staff can optionally create a voice channel for interviews.
- Once approved or denied, the temporary interview VC is removed.
- Staff commands include:
  - `/vcheck [user]` — View a user's verification details
  - `/vunverify [user]` — Remove a user's verification
  - `/vreferral [status]` — Show latest 50 verified or unverified referrals

---

## Admin experience

Admins can configure the system and manage channels.
Important commands:

- `/vinfo` — Show verification configuration
- `/vreferral [status]` — Show latest 50 referrals
- `/vreferrals` — Show latest 50 referrals with pagination
- `/vsetmexcapi` — Configure the MEXC API key and secret
- `/vchannel` — Set verification channel
- `/vpanel` — Send verification panel
- `/vpaneledit` — Edit the most recently created panel
- `/vcategory` — Set interview VC category
- `/vsetpending` — Set pending channel
- `/vsetapproved` — Set approved channel
- `/vsetdenied` — Set denied channel
- `/vrole [@role]` — Set verified role
- `/vaddstaff [@role]` — Add staff role
- `/vremovestaff [@role]` — Remove staff role
- `/vcooldown` — Set cooldown
- `/vdeletetoggle` — Toggle auto deletion of non-staff messages in verification channel
- `/vactive` — Configure active trading period

---

## Owner experience

Owner and trusted users can manage API credentials and exports.

- `/vsetmexcapi` — Configure the MEXC API key and secret
- `/vreferral [Status]` — Show verified/unverified referrals
- `/vreferrals` — Show latest 50 referrals with export option
- `/vreferralexport` — Export all MEXC referral data to CSV
- `/vreferralinfo [user]` — View a user's MEXC details
- `/vapprovetoggle` — Toggle automatic approval

---

## Key integration points

### Configuration

The bot reads its runtime settings from `config.json`.
The file contains:

---

- role IDs for staff and verified users
- channel IDs for verification and review flows
- verification cooldown and active trading window
- panel message IDs and trusted user IDs


### MEXC API usage

The bot queries the MEXC referral endpoint:

```text
https://api.mexc.com/api/v3/rebate/affiliate/referral?{query}&signature={signature}
```


### MEXC API Response Keys

The API returns referral data with the following keys (15 keys found):

- asset
- commission
- depositAmount
- email
- firstDepositTime
- firstTradeTime
- identification
- inviteCode
- lastDepositTime
- lastTradeTime
- nickName
- registerTime
- tradingAmount
- uid
- withdrawAmount

## Command summary

### User commands

- `/verify` — Submit your MEXC UID for verification
- `/vmyinfo` — View your own verification details

### Staff commands

- `/vcheck [user]` — View a user's verification details
- `/vunverify [user]` — Remove a user's verification
- `/vreferral [status]` — Show the latest 50 referrals

### Admin commands

- `/vinfo` — Show verification configuration
- `/vreferral [status]` — Show the latest 50 referrals
- `/vchannel` — Set verification channel
- `/vpanel` — Send verification panel
- `/vpaneledit` — Edit the most recently created panel
- `/vcategory` — Set interview VC category
- `/vsetpending` — Set pending channel
- `/vsetapproved` — Set approved channel
- `/vsetdenied` — Set denied channel
- `/vrole [@role]` — Set verified role
- `/vaddstaff [@role]` — Add staff role
- `/vremovestaff [@role]` — Remove staff role
- `/vcooldown` — Set cooldown
- `/vdeletetoggle` — Toggle auto deletion
- `/vactive` — Configure active trading period

### Owner commands

- `/vsetmexcapi` — Configure the MEXC API key and secret
- `/vreferral [Status]` — Show the latest 50 referrals
- `/vreferrals` — Show the latest 50 referrals with pagination
- `/vreferralexport` — Export all MEXC referral data to CSV
- `/vreferralinfo [user]` — View a user's MEXC details
- `/vapprovetoggle` — Toggle auto approval

## Usage notes

- This repo is a public showcase of a Discord verification via MEXC Referral.
- What is shared here is enough to understand the API integration, configuration, and bot behavior.
- Minor bugs may exist – feel free to modify and improve it.

---

# Screenshot Gallery

##Below are placeholder screenshot files for the verification workflow. Update these image files in `showcase/images/` with your real screenshots.

### Verification Panel
Main verification panel where users can start the MEXC referral verification process.

![Verification Panel](showcase/images/01-referral-panel.png)

### UID Input Modal
Modal where users enter their MEXC UID for verification.

![UID Input Modal](showcase/images/02-verify-modal.png)

### Invalid UID Result
Shown when the entered UID is not found under the configured referral list.

![Invalid UID Result](showcase/images/03-invalid-uid.png)

### Successful Verification
User UID was found in the referral system and the verified role was assigned successfully.

![Successful Verification](showcase/images/04-uid-found.png)

### Approved User DM
Direct message automatically sent to users after being verified.

![Approved User DM](showcase/images/05-dm-approved.png)

### Referral Approved Confirmation
Confirmation message shown after the referral verification is approved.

![Referral Approved Confirmation](showcase/images/06-referral-approved.png)

### Pending Review Notice
Displayed when auto-approve is disabled and the request is sent for manual staff review.

![Pending Review Notice](showcase/images/07-pending-review.png)

### Review Action Controls
Buttons and controls available for staff handling pending verification requests.

![Review Action Controls](showcase/images/08-review-controls.png)


# Staff Features

### Approved Logs Channel
Message sent to the approved logs channel after successful verification.

![Approved Logs Channel](showcase/images/09-approved-channel.png)

### Verified Referral List
Display of `/vreferral verified` command showing verified referrals.

![Verified Referral List](showcase/images/10-vreferral-verified.png)

### User Verification Check
Result of `/vcheck [user]` command displaying a user's verification status.

![User Verification Check](showcase/images/11-vcheck-user.png)


# Admin Features

### Admin Commands Overview
Overview of available administrator commands.

![Admin Commands Overview](showcase/images/12-admin-commands.png)

### Unauthorized CSV Export Attempt
Error shown when an unauthorized admin attempts to export CSV data.

![Unauthorized CSV Export Attempt](showcase/images/13-export-csv-blocked.png)


# Owner Features

### Instant CSV Export
Instant export feature available only to the owner or trusted users.

![Instant CSV Export](showcase/images/14-insta-export.png)

### MEXC API Setup - Page 1
First page of the `/vsetmexcapi` setup interface.

![MEXC API Setup Page 1](showcase/images/15-vsetmexcapi-page1.png)

### MEXC API Setup - Page 2
Second page of the `/vsetmexcapi` setup interface.

![MEXC API Setup Page 2](showcase/images/16-vsetmexcapi-page2.png)

### MEXC API Setup Modal
Modal used to input API credentials and configuration.

![MEXC API Setup Modal](showcase/images/17-vsetmexcapi-modal.png)

### MEXC API Setup - Page 3
Final page of the `/vsetmexcapi` setup process.

![MEXC API Setup Page 3](showcase/images/18-vsetmexcapi-page3.png)


# Manual Review System

### Staff Review Channels
Dedicated channels used by staff for handling verification reviews.

![Staff Review Channels](showcase/images/19-staff-review-channels.png)

### Verification Sent for Review
Verification request being forwarded to the review queue.

![Verification Sent for Review](showcase/images/20-sent-staff-review.png)


# Pending Review Actions

### Verify or Deny Request
Staff members can approve or deny verification requests directly from the pending review message.

![Verify or Deny Request](showcase/images/21-pending-actions.png)

### Create Interview VC
Option to create a temporary voice channel for interviewing the applicant.

![Create Interview VC](showcase/images/22-create-vc.png)

### Applicant DM Notifications
DM notifications sent to the applicant regarding interview VC actions.

![Applicant DM Notifications](showcase/images/23-vc-removed.png)


# Verified User Features

### User Verification Information
Verified users can view their linked MEXC account information using `/vmyinfo`.

![User Verification Information](showcase/images/24-vmyinfo.png)
