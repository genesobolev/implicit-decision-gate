Add expiration support to share links.
Store it in public.share_links.expires_at as a nullable timestamp with time zone.
New share links should expire 30 days after creation.
