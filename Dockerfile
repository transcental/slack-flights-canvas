# Step 1: Build Stage
FROM node:18-slim AS builder

WORKDIR /app

# Copy package files first to leverage Docker cache
COPY package*.json ./
RUN npm install

# Copy the rest of the source code
COPY . .

# Build the TypeScript code (converts /src to /dist or /build)
RUN npm run build

# Step 2: Production Stage
FROM node:18-slim

WORKDIR /app

# Only copy the production dependencies and the compiled files
COPY --from=builder /app/package*.json ./
RUN npm install --omit=dev

COPY --from=builder /app/dist ./dist

# Set environment to production
ENV NODE_ENV=production

# The command to start the Slack bot
CMD ["npm", "start"]
