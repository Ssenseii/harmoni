# Changelog

All notable changes to this project will be documented in this file.

## [1.3.0] - 2026-11-05

### Added
- **Spotify setup guidance**: When Spotify is not configured, a step-by-step guide opens the Spotify dashboard, lets you copy the redirect URI, and takes you to the Client ID field, instead of silently switching to Exportify.
- **Sidebar quick actions**: Start Downloads, Retry Failed and Open Music Folder are always one click away, with queue counts.
- **Failure reasons**: Failed downloads show why they failed in the queue, including when a track is age-restricted and needs browser cookies.
- **Open any public Spotify link**: Paste a playlist, album or track link on the Spotify page and it loads without a Spotify developer app. Playlists you follow but don't own load the same way. Spotify's public page lists up to 100 tracks and no album names.
- **Notice bar**: Confirmations like "added to queue" and "settings saved" show in a bar that fades out instead of a popup you have to close.
- **CI tests and secret scanning**: Every push and pull request runs the unit tests and a gitleaks scan, and release builds only start when both pass. A gitleaks pre-commit hook is included.
- **Example data files**: `data/tracks.example.json` and `data/playlists.example.json` show the expected formats.

### Fixed
- **Spotify connection**: The automatic Exportify fallback is gone. Errors say what went wrong, the client is updated for the February 2026 Web API changes, and playlists you follow but do not own are marked as unreadable through the API, with a pointer to Exportify, instead of failing when you open them.
- **Downloads**: Cancel now stops the running download. The failed downloads list and resume work again. YouTube results are matched against the track duration so wrong versions are picked less often.
- **Downloads with cookies**: Signed-in YouTube needs a JavaScript runtime, so HARMONI now passes Deno or Node 20+ to yt-dlp automatically. Without one, every cookie download failed. Failed searches also retry with other YouTube clients and a simpler title.
- **Settings**: Scrolling no longer changes the format and template boxes, and the save bar stays visible at the bottom.
- **Data files**: JSON data is written atomically, so a crash can no longer leave a half-written file. Data and config paths are anchored to the app folder, so they no longer depend on the folder you launch from.
- **Startup**: The app starts faster and no longer flashes console windows on Windows.
- **Spotify and queue UI**: Playlists open with a single click, adding tracks says that downloads wait for Start Downloads, and selected rows no longer show Windows 11 accent bars.
- **Release builds**: Personal data from `data/` is no longer bundled into the release binaries, and a tag build fails if `version.py` does not match the tag.

### Why
- These changes address Ssenseii/harmoni#42, #44, #45 and #46.
- A silent Exportify fallback hid the real Spotify error, so users could not tell what to fix.
- Cancel, resume and the failed list are basic controls for long batch downloads, and they did not work reliably.
- Personal playlists and download history were tracked in git and shipped inside release builds. They are now ignored, and CI scans for secrets so tokens cannot be committed again.

## [1.2.0] - 2026-07-30

### Added
- **Custom yt-dlp / ffmpeg arguments**: You can now pass extra CLI flags straight through to yt-dlp and ffmpeg for every download:
  - New `ytdlp_extra_args` and `ffmpeg_extra_args` config fields (ffmpeg args are forwarded via yt-dlp's `--postprocessor-args`)
  - New "Extra yt-dlp arguments" / "Extra ffmpeg arguments" fields in the GUI Settings view, under Download Settings
  - Editable from the CLI config menu like any other setting
  - Applied consistently across all download paths: track/batch downloads, retries, and direct link/playlist downloads
- **Disconnect button for Spotify**: The Spotify view now has a "Disconnect" button next to Connect, so you can clear the cached token and re-auth without digging through files.

### Fixed
- **Duplicate-detection and metadata matching for special/reserved characters**: Filenames with characters yt-dlp sanitizes (`: * / \ < > | " ?`) or full-width unicode variants no longer cause tracks to be re-downloaded or fail metadata embedding. Matching is now done via a normalized key (`utils/filename_match.py`) instead of exact/prefix string comparison, in `downloader/metadata.py` and `utils/track_checker.py`.
- **Bundled yt-dlp binary was being stripped on macOS/Linux builds**, breaking every download on those platforms. The build workflow and `build-macos.sh` no longer strip it.

### Why
- Passing custom flags was the most requested missing feature: without something like `--cookies cookies.txt`, large playlist downloads get rate-limited/timed out by YouTube. Power users can now also tweak ffmpeg output (e.g. sample rate) without touching code.
- The filename-matching fix prevents silent re-downloads/duplicate work for tracks whose titles contain characters that get sanitized differently across yt-dlp versions/platforms.
- The macOS/Linux build fix was a release blocker — every download failed post-build until yt-dlp was no longer stripped.

### Compatibility
- Fully backward compatible with older `config.json` files. Missing keys are backfilled with empty defaults on load, so existing configs keep working unchanged and no extra arguments are applied unless explicitly set.

## [1.1.0] - 2026-03-03

### Added
- **yt-dlp Update Checker & Installer**: Implemented a comprehensive update system for yt-dlp with:
  - Automatic update detection through the update checker module
  - In-app notifications to alert users when updates are available
  - One-click installer for seamless yt-dlp updates
  - New `ytdlp_updater.py` worker module handling update logic in GUI thread

### Changed
- **Settings View**: Now automatically reloads configuration on save and updates the UI to reflect changes immediately
- **Spotify Integration**: Refactored token expiration checking to use the TokenManager, improving code maintainability and centralizing token lifecycle management
- **Main Window**: Updated to support the new yt-dlp update checker integration

### Why
These changes were made to improve user experience and code quality:
1. Users can now keep yt-dlp updated without manual intervention, ensuring access to the latest features and bug fixes
2. Settings changes take immediate effect without requiring app restart (I think you'll have to reload the app after installing yt-dlp because visually it shows not installed)
3. Centralized token management through TokenManager reduces duplication and potential bugs in token handling across different parts of the application
4. when you open the app, there will be some quick cli openings which is a bit scary but don't worry, it's just small scripts to check for things if they are there or not.

## [1.0.0] - 2026-01-01

### Added
- Initial stable release of Harmoni
- GUI version 1.0.0 with core features
- Initial yt-dlp update checker foundation
