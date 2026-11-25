# Steele Family Recipe Vault

A family recipe box. Save recipes from links (Instagram, TikTok, YouTube, Pinterest or a recipe site), keep photos and videos with each recipe, and build a shopping list from the ingredients.

## What it does

- **Import from a link.** Recipe sites give a full recipe (ingredients and steps). Social posts give the title, caption and photo, and the original link is kept. The recipe photo is copied into the app, so it doesn't break if the site changes.
- **Share from your phone (Android Chrome).** Once the app is on your home screen, use the Share menu and pick Steele Family Recipe Vault. You can share a link, or a saved video or screenshot from TikTok or Instagram. The file becomes a new recipe that you finish in Edit. iPhone can't share files into web apps, so there, upload the video through the Videos field.
- **Embedded posts.** YouTube, TikTok and Instagram links play inside the recipe page.
- **Mixed media.** Each recipe can hold photos, videos and links, with a choice of cover photo.
- **Shopping list.** Tick ingredients on a recipe and add them. Duplicates are skipped. Tick items off in the store.
- **Stays signed in.** The sign-in page remembers the device for a year, so the password is only needed once per device.
- **Search, tags, family ratings and a backup download** that includes every recipe, plus all photos and videos.

## Run it on your computer (optional)

```
cd C:\Users\Aaron\recipe-keeper
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Then open http://localhost:5000.

## Deploy on Railway

The app is already deployed from GitHub. These are the settings it needs:

- A volume mounted at `/data`, with `DATA_DIR=/data`.
- `APP_PASSWORD` (family password) and `SECRET_KEY` (a long random string). Keep `SECRET_KEY` fixed. If it changes, every device has to sign in again.
- `MAX_UPLOAD_MB` (optional, default 300).

Pushing to `main` on GitHub redeploys automatically.

## Where things live

- Recipe fields and routes: `app.py`. Shared-file saving is `save_shared`.
- Link import, photo copying and embed rules: `importers.py`.
- Look, colors and motion: `static/style.css`. Tab highlight: `static/app.js`.
- Phone share settings: `static/manifest.webmanifest`.

## Limits to know about

- Instagram and TikTok often hide captions and recipe text from link previews. For those posts, paste the caption into the Ingredients and Steps boxes.
- Downloading videos straight from TikTok or Instagram isn't supported. Save the video in the app, then share it.
- Photos and videos are stored on the Railway volume. Use the Backup link now and then.
