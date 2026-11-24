# musicgit

A tiny, git-style sync tool for YouTube Music playlists. The playlist folder is
your working tree, a snapshot of the playlist is its last known upstream state,
and `pull` downloads only what is missing — so re-running it is always safe and
picks up songs you added to the playlist since last time.

No dependencies beyond `yt-dlp` and `ffmpeg`. `python-mutagen` (`pacman -S
python-mutagen`) is optional: with it, tags and cover art are embedded; without
it, musicgit still downloads the same audio and just skips the tagging step.

## Quick start

```bash
musicgit init ~/Music/library
cd ~/Music/library

musicgit remote add faves 'https://music.youtube.com/playlist?list=PL...'
musicgit remote add gym   'https://music.youtube.com/playlist?list=PL...'

musicgit pull -j 4        # download everything missing
musicgit status           # what changed upstream since the last pull
musicgit failed           # every song that failed, with the reason
musicgit retry            # try just those again
```

`musicgit` also works without `cd` by using `-C DIR`, like git:

```bash
musicgit -C ~/Music/library pull
```

## Commands

| Command | What it does |
|---|---|
| `init [dir]` | create an empty library repo |
| `remote add <name> <url>` | track a playlist (a bare ID also works) |
| `remote list` / `remote remove <name>` | show / stop tracking (files are kept) |
| `fetch [remote]` | refresh playlist snapshots, download nothing |
| `status [remote]` | diff last snapshot vs. disk: `+ new`, `- gone upstream`, `! failed` |
| `playlist [remote]` | rewrite `playlist.m3u8` from the snapshots and disk, no network |
| `pull [remote]` | fetch, then download every missing song; reports failures |
| `pull --prune` | also move songs deleted upstream into `.musicgit/removed/` |
| `pull --dry-run` | show what would be downloaded |
| `retry [remote]` | re-download only the songs listed in `.musicgit/failures.json` |
| `retry --search` | if a video is deleted, download the best alternate upload instead |
| `retry --only <id,id>` | retry just these video ids |
| `failed [--json]` | list failures with their yt-dlp reason |
| `retag [remote]` | strip YouTube's ` - Topic` suffix from artist tags (helps lyric lookup) |
| `log [-n N]` | history of fetches and pulls |
| `config` | show/change `--audio-format`, `--cookies-from-browser`, `--cookies-file`, `--id-in-filename` |

`-j/--jobs N` on `pull` and `retry` downloads N songs at once (default 1).

## Quality

Audio comes from the best stream YouTube serves and is **remuxed, never
re-encoded** (`-f bestaudio/best -x --audio-format best`), with metadata and
cover art embedded. YouTube Music caps audio at ~128 kbps anonymously; a Premium
account doubles that, so for the highest bitrate:

```bash
musicgit config --cookies-from-browser firefox   # or chrome, brave, ...
```

Converting to FLAC would only make the files bigger, not better.

## One folder for all songs

By default each playlist keeps its own songs. To collect every playlist's audio
in a single folder instead, point `songs_dir` at it (relative to the repo, or
absolute) and regenerate the playlists:

```bash
musicgit config --songs-dir ../songs      # or an absolute path
musicgit playlist                         # rewrite every playlist.m3u8
```

Entries in `playlist.m3u8` are always relative to the playlist file, so they
become `../../songs/<file>.opus`. Downloads land in the songs dir and a song
shared by two playlists is only stored once. `--prune` is skipped in this mode,
since a shared folder cannot tell which playlist dropped a song.

## Output layout

```
~/Music/library/
├── The cedar Creek files/                    <- folder named after the playlist
│   ├── 001 - Artist - Title.opus            <- [VIDEO_ID] only if --id-in-filename is on
│   ├── playlist.m3u8                         <- current upstream order (paths relative to it)
│   └── .incoming/                            <- scratch space during downloads
└── .musicgit/
    ├── config.json        remotes + settings
    ├── snapshots/<name>.json   last seen playlist state
    ├── failures.json      songs that failed, with reasons
    ├── failures.md        same, human readable
    ├── removed/<name>/    songs dropped upstream (only with --prune)
    └── log.jsonl          sync history
```

Filenames carry the video ID, which is how a song is matched to its playlist
entry no matter how the title changes. Folder names are fixed on first fetch, so
renaming a playlist upstream never orphans your files.

## Tests

The suite runs against `tests/fake-ytdlp`, so it needs no network:

```bash
cd Projects/musicgit && python3 -m unittest discover -s tests -v
```

## If everything fails with a certificate error

`musicgit` prints the certificate `www.youtube.com` actually presents. If the
issuer is not Google, a proxy or content filter is intercepting YouTube TLS and
yt-dlp cannot read playlists or download audio until that root CA is trusted or
you use another network.
