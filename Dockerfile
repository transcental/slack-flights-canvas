# Step 1: Build Stage
FROM node:18-slim AS builder

WORKDIR /app

COPY package*.json ./
RUN npm install

COPY . .

# Run the build script
RUN npm run build

# SAFETY CHECK: List files to verify if it's 'build' or 'dist'
RUN ls -la

# Step 2: Production Stage
FROM node:18-slim

WORKDIR /app

# Only copy production dependencies
COPY --from=builder /app/package*.json ./
RUN npm install --omit=dev

# Copy the compiled code from 'build' (the correct folder for this repo)
COPY --from=builder /app/build ./build

ENV NODE_ENV=production

# Start the bot using the compiled code
CMD ["node", "build/index.js"]
