CREATE TABLE public.share_links (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    token text NOT NULL UNIQUE,
    created_at timestamp with time zone NOT NULL DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO public.share_links (token) VALUES ('existing-fixture');
