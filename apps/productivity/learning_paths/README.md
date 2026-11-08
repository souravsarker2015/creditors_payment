The ready-made learning roadmaps (Productivity → Learning roadmaps), one per file,
written as an outline that `apps/productivity/paths.py` reads (people can paste the
same outline, or the JSON format, to make their own):

    title: Backend developer
    category: role | skill | language
    color: blue            (one of the app's colours)
    about: One line on what it covers.

    # A step on the main path :: what it is, in a sentence
    @ A resource | https://…
    - A topic under it :: …
      - A smaller topic under that one :: …
    - ?An optional topic (the ? marks it optional) :: …
    ! A checkpoint: something to build :: …

Order matters: the steps run top to bottom; `@` lines add a link to the line above.
