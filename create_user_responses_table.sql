-- Create user_responses table for user-specific article labeling
CREATE TABLE IF NOT EXISTS user_responses (
    id SERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    article_id INTEGER NOT NULL,
    label VARCHAR(20) NOT NULL CHECK (label IN ('positive', 'negative', 'neutral')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    -- Foreign key constraint
    FOREIGN KEY (article_id) REFERENCES articles(id) ON DELETE CASCADE,
    
    -- Unique constraint: one response per user per article
    UNIQUE(user_id, article_id)
);

-- Create index for faster queries
CREATE INDEX IF NOT EXISTS idx_user_responses_user_id ON user_responses(user_id);
CREATE INDEX IF NOT EXISTS idx_user_responses_article_id ON user_responses(article_id);
CREATE INDEX IF NOT EXISTS idx_user_responses_created_at ON user_responses(created_at);

-- Add trigger to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_user_responses_updated_at 
    BEFORE UPDATE ON user_responses 
    FOR EACH ROW 
    EXECUTE FUNCTION update_updated_at_column(); 