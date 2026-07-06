# WAYPOINT
### The Smart Operations Companion for Model Railroaders

> **What is Waypoint?**
> Waypoint is a web-based management tool that brings real railroad operations to your model layout. It tracks your rolling stock, automates waybill routing, and guides every car through a prototypical operating session — so you can focus on the fun part.

---

> **Key Facts**
> - AI identifies car type, reporting marks, road number, and color from a single photo
> - Supports Claude, GPT-4o, Gemini, and local Ollama vision models
> - Waybill cards support up to 4 sequential movements per car
> - Fast clock simulates prototypical railroad time at 1×, 2×, 4×, 6×, or 12× speed
> - Full layout backup and restore in a single ZIP file — car photos included
> - Real-time crew notifications keep dispatchers and operators in sync across devices

---

## Smart Car Roster

Build your fleet in minutes, not hours.

- Photograph any car — AI instantly fills in car type, reporting marks, road number, and color
- Choose your AI engine: Claude (Anthropic), GPT-4o (OpenAI), Gemini, or a local Ollama model
- Generate a stylized illustration of each car with one click
- Add cars manually or select photos from a shared library
- Edit any detail at any time; delete cars cleanly with full history cleanup
- **Photo Library** — view all uploaded car images in a grid; hover any photo to download or delete it; default images are protected from deletion

---

## Waybill System

Prototype-accurate car routing without the paperwork.

- Create waybills with origin, destination, commodity, and assigned industry
- Stack up to 4 sequential movement cards on a single car
- Generate waybills automatically from your layout's industries
- Auto-assign unassigned waybills to available cars by car type and routing logic
- Define commodity-to-car-type rules (e.g. grain → covered hopper, crude oil → tank car)
- Advance a car's active waybill slot with a single tap

---

## Layout Setup

Model your railroad once, operate it forever.

- Define locations by type: Yard, Industry, Staging, or Storage
- Create industries and assign roles: Consumer (receives), Producer (ships), or Transload (both)
- Use ✨ AI Suggest to automatically fill in commodities, car types, and role from an industry name
- Specify which car types and commodities each industry accepts
- Seed a starter set of commodity mappings or build your own from scratch
- Use ✨ on any commodity to get an AI suggestion for the correct car type
- Collapse the Commodity → Car Type panel to save space when not in use
- Configure the Fast Clock start time and speed multiplier

---

## Operating Sessions

Run a realistic ops session from plan to wrap-up.

- Session planner lists every car move needed: arrivals, departures, and cars to spot from storage
- Car thumbnails and reporting marks visible at a glance in the switch list
- Mark each car Done (moved) or CP (Car Placement — temporary hold)
- End session: waybill slots auto-advance and car locations update automatically
- Session state persists across browser refresh — pick up where you left off
- Read-only operations view shows every car, its current location, and active waybill

---

## Virtual Dispatcher

Build and manage capacity-aware consists directly from the Operations tab.

- **Multiple consists** — build as many consists as needed simultaneously, one per origin/switching area pair. Each appears as a collapsible card in the Dispatcher panel.
- **Train identity** — assign a train number, name, departure time, engineer, and conductor to each consist. The identity appears in the session header when the session starts.
- **Operations mode** — set the layout protocol in Layout Setup: Free, Timetable & Train Order (TT&TO), or Track Warrant Control (TWC). The label on the special instructions field updates accordingly ("Notes", "Train Order", or "Track Warrant").
- **Power assignment** — assign locomotives and a caboose to each consist. A consist cannot start a session without at least one locomotive assigned. The same locomotive cannot be assigned to two consists at once.
- **Status lifecycle** — each consist moves through Ready → active → complete. Status is shown as a colour badge on the card header.
- **Car claiming** — cars already assigned to one consist are automatically excluded when building another.
- **Rebuild** — click Rebuild on any card to re-run the build algorithm for that consist's origin and area, refreshing the car list while preserving identity, power, and crew.
- **Start session** — click Start Session on a consist card to hand it off to the Quick Op workflow. If a session is already running in that browser, a confirmation prompt appears before replacing it.

---

## Live Crew Notifications

Keep every operator in the loop without interrupting the session.

- Real-time events are pushed instantly to all connected browsers via Server-Sent Events (SSE)
- Notifications appear as non-intrusive toasts — no manual refresh needed
- **Session started** — crew members see a toast when the dispatcher opens a session, including car count
- **Session ended** — crew members see a summary when the session is closed
- **Consist created** — notifies all operators when a new dispatch plan is built
- **Crew assigned** — notifies when an engineer or conductor is named on a consist
- **Status change** — notifies when a consist goes active or completes
- Self-suppression: your own actions do not produce a notification for you
- Reconnects automatically if the connection drops

---

## Fast Clock

Simulate prototypical railroad time during every operating session.

- Fast clock starts automatically when a session begins; if a session is already running in another browser tab, the existing clock continues uninterrupted
- Configure start time (e.g. 08:00) and speed multiplier in Layout Setup
- Speed options: 1× (real time), 2×, 4×, 6×, or 12×
- Pause and resume the clock at any time during a session
- Click **↺** in the session header to reset the clock back to the configured start time; all connected browsers re-sync within 15 seconds
- Clock state is stored server-side — resuming after a page refresh shows the correct model time
- Supports multiple operators: all clients read from the same authoritative clock, re-syncing every 15 seconds

---

## AI Features

Reduce manual data entry at every step.

- **Car identification** — Upload a photo and AI fills in car type, reporting marks, road number, and color
- **Stylized illustration** — Generate an artistic rendering of any car with one click
- **Industry suggest** — Type an industry name and click ✨ AI Suggest to auto-fill commodities, car types, and role
- **Commodity suggest** — Click ✨ next to any commodity to get the correct car type automatically
- AI calls automatically retry on transient provider errors (rate limits, overloads) before failing
- Supported providers: Gemini, Claude (Anthropic), GPT-4o (OpenAI), or a local Ollama model

---

## Settings & Account

- **Tenant display name** — admins can update the layout's display name at any time from Settings
- **Invite operators** — send email invitations to crew members; assign operator or admin role
- **AI provider** — choose and configure your preferred vision model from Settings
- **Password reset** — operators can request a reset link from the login screen; no admin action required

---

## Data & Backup

Your layout data, safe and portable.

- Export a complete snapshot: locations, industries, cars, waybills, photos, and movement logs — car photos are downloaded from cloud storage and bundled into the ZIP
- Restore any backup with a single import — photos are re-uploaded to your tenant's storage automatically; no broken image links after restore
- Purge orphaned photos to keep storage tidy
- Per-car movement history records the last 5 moves with timestamps and notes
