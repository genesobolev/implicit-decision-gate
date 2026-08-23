Add 30-day expiration support to the fictional service behind 1Password item-sharing
links.

Store expiration in `public.share_links.expires_at` as a nullable timestamp with time
zone. New item-sharing links must expire 30 days after creation.
