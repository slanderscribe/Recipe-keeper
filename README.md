# Recipe Keeper

A family recipe box. Save recipes from links (Instagram, TikTok, YouTube, Pinterest or a recipe site), store photos and videos with each recipe, and build a shopping list from the ingredients.

## What it does

- **Import from a link.** Paste a post or recipe link. Recipe sites give a full recipe (ingredients and steps). Social posts give the title, caption and photo, and the original link is kept.
- **Share from your phone (Android Chrome).** Once the app is on your home screen, use the Share menu and pick Recipe Keeper. The link opens the import screen.
- **Embedded posts.** YouTube, TikTok and Instagram links play inside the recipe page.
- **Mixed media.** Each recipe can hold photos, videos and links. Choose a cover photo.
- **Shopping list.** Tick ingredients on a recipe and add them. Duplicates are skipped. Tick items off in the store.
- **Search, tags and family ratings.**
- **Backup.** The Backup link downloads a zip with every recipe (as JSON) plus all photos and videos.

## Run it on your computer (optional)

```
cd C:\Users\Aaron\recipe-keeper
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Then open http://localhost:5000.

## Put it on GitHub

```
cd C:\Users\Aaron\recipe-keeper
git init
git add .
git commit -m "Initial Recipe Keeper app"
git branch -M main
git remote add origin https://github.com/slanderscribe/recipe-keeper.git
git push -u origin main
```

Create the empty repo `recipe-keeper` on GitHub first.

## Deploy on Railway

1. In Railway, choose **New Project → Deploy from GitHub repo** and pick `recipe-keeper`.
2. Open the service, go to **Settings → Volumes**, add a volume, and set the mount path to `/data`. This keeps the database and photos safe across redeploys.
3. Go to **Variables** and add:
   - `DATA_DIR` = `/data`
   - `APP_PASSWORD` = the family password
   - `SECRET_KEY` = any long random text (for example, 40 random letters and numbers)
   - `MAX_UPLOAD_MB` = `300` (optional)
4. Go to **Settings → Networking** and generate a domain. Open it on your phone and sign in.

## Adding features later

- Recipe fields live in `app.py` (`recipe_from_form`) and in `templates/recipe_form.html`.
- Import rules for each site live in `importers.py`. Recipe sites that publish schema.org data work best.
- Look and colors are in `static/style.css`.

## Limits to know about

- Instagram and TikTok often hide captions and recipe text from link previews. For those posts, paste the caption into the Ingredients and Steps boxes.
- Photos and videos are stored on the Railway volume, so the volume should be backed up with the Backup link now and then.
