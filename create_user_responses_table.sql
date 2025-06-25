CREATE TABLE IF NOT EXISTS user_responses (
    id SERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    uri TEXT NOT NULL,
    response TEXT NOT NULL CHECK (response IN ('like', 'dislike')),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Create index for faster lookups
CREATE INDEX IF NOT EXISTS idx_user_responses_user_id ON user_responses(user_id);
CREATE INDEX IF NOT EXISTS idx_user_responses_uri ON user_responses(uri); 