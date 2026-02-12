/**
 * K6 Load Test: Parallel Jobs
 * 
 * Simulates 100 concurrent users creating jobs simultaneously
 * 
 * Usage:
 *   k6 run --vus 100 --duration 5m parallel_jobs.js
 */

import http from 'k6/http';
import { check, sleep } from 'k6';
import { Rate, Trend } from 'k6/metrics';

// Custom metrics
const jobCreationRate = new Rate('job_creation_success');
const jobLatency = new Trend('job_completion_latency');

// Configuration
const BASE_URL = __ENV.BOT_API_URL || 'http://localhost:8080';
const BOT_TOKEN = __ENV.BOT_TOKEN || 'test_token';

export const options = {
    stages: [
        { duration: '1m', target: 20 },   // Ramp up to 20 users
        { duration: '2m', target: 100 },  // Ramp up to 100 users
        { duration: '5m', target: 100 },  // Stay at 100 users
        { duration: '1m', target: 0 },    // Ramp down
    ],
    thresholds: {
        'http_req_duration': ['p(95)<5000'],  // 95% of requests under 5s
        'job_creation_success': ['rate>0.995'], // 99.5% success rate
        'job_completion_latency': ['p(95)<180000'], // 95% under 180s
    },
};

// Test data
const prompts = [
    'A beautiful sunset over mountains',
    'A cat wearing a space suit',
    'Abstract art with vibrant colors',
    'Futuristic city at night',
    'Peaceful forest landscape',
];

export default function () {
    const userId = `user_${__VU}`;
    const prompt = prompts[Math.floor(Math.random() * prompts.length)];
    
    // 1. Create image generation job
    const createJobPayload = JSON.stringify({
        user_id: userId,
        type: 'image_generation',
        prompt: prompt,
    });
    
    const createJobRes = http.post(
        `${BASE_URL}/api/jobs/create`,
        createJobPayload,
        {
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${BOT_TOKEN}`,
            },
        }
    );
    
    const jobCreated = check(createJobRes, {
        'job created': (r) => r.status === 200,
        'job_id returned': (r) => JSON.parse(r.body).job_id !== undefined,
    });
    
    jobCreationRate.add(jobCreated);
    
    if (!jobCreated) {
        console.error(`Job creation failed: ${createJobRes.status} ${createJobRes.body}`);
        sleep(1);
        return;
    }
    
    const jobId = JSON.parse(createJobRes.body).job_id;
    const startTime = Date.now();
    
    // 2. Poll job status
    let jobCompleted = false;
    let attempts = 0;
    const maxAttempts = 60; // 5 minutes max
    
    while (!jobCompleted && attempts < maxAttempts) {
        sleep(5); // Poll every 5 seconds
        attempts++;
        
        const statusRes = http.get(
            `${BASE_URL}/api/jobs/${jobId}/status`,
            {
                headers: {
                    'Authorization': `Bearer ${BOT_TOKEN}`,
                },
            }
        );
        
        if (statusRes.status === 200) {
            const status = JSON.parse(statusRes.body).status;
            
            if (status === 'completed') {
                jobCompleted = true;
                const latency = Date.now() - startTime;
                jobLatency.add(latency);
            } else if (status === 'failed') {
                console.error(`Job ${jobId} failed`);
                break;
            }
        }
    }
    
    if (!jobCompleted) {
        console.warn(`Job ${jobId} did not complete within timeout`);
    }
    
    sleep(Math.random() * 5); // Random delay between iterations
}

export function handleSummary(data) {
    return {
        'summary.json': JSON.stringify(data, null, 2),
        stdout: textSummary(data, { indent: ' ', enableColors: true }),
    };
}

function textSummary(data, options) {
    const indent = options.indent || '';
    const enableColors = options.enableColors || false;
    
    let summary = '\n';
    summary += `${indent}Test Summary:\n`;
    summary += `${indent}  Total Requests: ${data.metrics.http_reqs.values.count}\n`;
    summary += `${indent}  Failed Requests: ${data.metrics.http_req_failed.values.passes}\n`;
    summary += `${indent}  Request Duration (p95): ${data.metrics.http_req_duration.values['p(95)']}ms\n`;
    summary += `${indent}  Job Creation Success Rate: ${(data.metrics.job_creation_success.values.rate * 100).toFixed(2)}%\n`;
    summary += `${indent}  Job Completion Latency (p95): ${data.metrics.job_completion_latency.values['p(95)']}ms\n`;
    
    return summary;
}
