-- Add progress column to goals table
ALTER TABLE goals ADD COLUMN progress INTEGER DEFAULT 0;
