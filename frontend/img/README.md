# Team photos

The footer's "The people behind Trailbit" section looks for photos here. If a file is missing, the tile shows the person's initials, so nothing looks broken.

| Tile | File |
|------|------|
| Bhuvan M (developer and maker) | `bhuvan-m.jpg` |
| Rajeeva MJ (contributor) | `rajeeva-mj.jpg` |

The two portraits above are the same ones published on the HaptiBraille team page, <https://rbksh.github.io/HaptiBraille/>.

**Replacing a photo**

Save a square-ish portrait over the existing file (JPG, about 400 to 600 px, under 300 KB is plenty) and reload the page. No code change is needed.

**Adding another contributor**

1. Put their photo here, for example `their-name.jpg`.
2. In `frontend/index.html`, inside `<section id="team">`, copy a `<li class="person">` block. Change the name, the role, the initials in `.photo-fallback`, the `alt` text, and `data-photo="img/their-name.jpg"`.
3. Tiles wrap automatically, so nothing else needs changing.

Only add photos of people who have agreed to be shown. This is a public repository.
