# Aircraft type photos added by hand

Photos in this folder are shown in the AIRCRAFT tab instead of the automatic ones, with the author's name as a
plain caption under the photo ("Photo: <author>") instead of a link.

## Files

- `<ICAO>.jpg`, `<ICAO>.jpeg`, `<ICAO>.png` or `<ICAO>.webp`: one photo per ICAO type code, for example
  `B738.jpg` or `A20N.webp`. Upper or lower case does not matter (`b738.JPG` works too). If a type has more than
  one photo here, the first in the order jpg, jpeg, png, webp is used.
- `<ICAO>.txt` (optional): the author of the photo on the first line, for example `Firstname Lastname` or
  `Firstname Lastname / Example Photo Group`. Save it as UTF-8. Only the first non-empty line is used, extra
  spaces and a leading `Photo:` are dropped, and the caption is cut at 120 characters. Without this file the photo
  is shown with no caption.

Example:

```
data/photos-manual/B738.jpg
data/photos-manual/B738.txt    ->  Firstname Lastname
```

## How it works

- A photo here always wins over everything in `data/photos/` (the automatic Wikipedia photos and older own
  photos). The application never moves, replaces or deletes files in this folder, and it does not ask Wikipedia
  for a type that has a photo here.
- The photo is shown in a fixed 3:2 frame (up to 450 x 300 px), scaled to fit without cropping. A landscape photo
  about 960 to 1280 px wide and under 500 KB looks best; small photos are enlarged and can look soft.
- Remove the photo (and its `.txt`) to go back to the automatic photo.

## Adding photos on the server

This folder is part of the repository and of the Docker image (it is not in the `data/photos` volume). Add the
files to the repository, for example on GitHub with "Add file" > "Upload files" into `data/photos-manual/`, and
deploy as usual (`sh deploy/update.sh`). A file copied into a running container with `docker cp` is lost at the
next rebuild.

Make sure you have the right to use each photo and name its author as the licence requires.
