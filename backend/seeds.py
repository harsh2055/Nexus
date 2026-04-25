TEAM = [
    ("t1", "Alex Johnson", "Project Lead", "alex@nexus.io", "linear-gradient(135deg,#E8A030,#C4862A)"),
    ("t2", "Sarah Chen", "Senior Developer", "sarah@nexus.io", "linear-gradient(135deg,#38BDF8,#0EA5E9)"),
    ("t3", "Marcus Rivera", "UI/UX Designer", "marcus@nexus.io", "linear-gradient(135deg,#34D399,#10B981)"),
    ("t4", "Priya Patel", "Backend Engineer", "priya@nexus.io", "linear-gradient(135deg,#F87171,#EF4444)"),
    ("t5", "Jordan Kim", "QA Engineer", "jordan@nexus.io", "linear-gradient(135deg,#C084FC,#A855F7)"),
    ("t6", "Lena Muller", "DevOps Engineer", "lena@nexus.io", "linear-gradient(135deg,#F472B6,#EC4899)"),
]

PROJECTS = [
    ("p1", "Nexus Platform Redesign", "A full dashboard redesign with refined navigation, faster workflows, and a reusable component system.", "#E8A030", "active", "2026-03-02"),
    ("p2", "Mobile App v2.0", "Native mobile application with offline support, push notifications, and biometric authentication.", "#38BDF8", "active", "2026-03-16"),
    ("p3", "API Gateway Migration", "Move client traffic to GraphQL with rate limiting, caching, and monitoring.", "#34D399", "active", "2026-03-22"),
    ("p4", "Analytics Dashboard", "Realtime business analytics with exportable reports and custom visualization presets.", "#C084FC", "planning", "2026-04-01"),
]

PROJECT_MEMBERS = {
    "p1": ["t1", "t2", "t3"],
    "p2": ["t1", "t4", "t5"],
    "p3": ["t4", "t6"],
    "p4": ["t2", "t3"],
}

TASKS = [
    ("k1", "p1", "Design new color system", "Create a cohesive palette and token map for the redesign.", "done", "high", "t3", "2026-04-08", ["design"]),
    ("k2", "p1", "Build component library", "Implement reusable UI components with examples.", "review", "critical", "t2", "2026-04-24", ["frontend"]),
    ("k3", "p1", "Implement theme switching", "Persist user theme preference and smooth transitions.", "progress", "medium", "t2", "2026-04-28", ["frontend"]),
    ("k4", "p1", "Dashboard layout restructure", "Rearrange widgets for quicker scanning.", "progress", "high", "t3", "2026-04-27", ["design"]),
    ("k5", "p1", "Performance audit", "Measure load time and interaction delays.", "todo", "low", "t2", "2026-05-02", ["performance"]),
    ("k6", "p2", "Set up React Native project", "Initialize project, linting, and navigation shell.", "done", "critical", "t4", "2026-04-13", ["setup"]),
    ("k7", "p2", "Implement authentication flow", "Login, registration, and biometric unlock.", "progress", "critical", "t4", "2026-04-30", ["auth"]),
    ("k8", "p2", "Offline data sync", "Local-first storage with a replayable sync queue.", "todo", "high", "t4", "2026-05-06", ["backend"]),
    ("k9", "p3", "Design GraphQL schema", "Define types, queries, mutations, and permissions.", "done", "critical", "t4", "2026-04-15", ["api"]),
    ("k10", "p3", "Implement rate limiter", "Token bucket algorithm backed by Redis.", "progress", "high", "t6", "2026-05-01", ["infra"]),
    ("k11", "p3", "Response caching layer", "Cache headers and CDN rules for common queries.", "review", "medium", "t6", "2026-05-03", ["infra"]),
    ("k12", "p4", "Requirements gathering", "Interview stakeholders and define primary KPIs.", "todo", "high", "t1", "2026-05-04", ["research"]),
    ("k13", "p4", "Chart component selection", "Evaluate charting libraries for rendering performance.", "todo", "medium", "t2", "2026-05-09", ["frontend"]),
]

