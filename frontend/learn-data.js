// Shared article manifest: what the Learn page, the homepage guide tiles and the sitemap list.
// The four guides below each have a hand-built page inside article.html (the rich templates, keyed by
// slug). To add a SIMPLE article instead: (1) create frontend/articles/<slug>.md (plain headings,
// paragraphs, bold/italic, links and bullet lists; see markdown.js), and (2) add an entry here.
// A slug needs one or the other, never both. video_youtube_id is optional - set it to a YouTube
// video ID (the part after "v=" in a youtube.com URL) once a video exists, or leave null.
const ARTICLES = [
  {
    slug: "what-is-ats",
    title: "How Applicant Tracking Systems Work",
    summary: "What they do, why it matters, and how to work with them.",
    category: "ATS Basics",
    video_youtube_id: null,
  },
  {
    slug: "resume-calling-card",
    title: "Your Resume Is Your Calling Card",
    summary: "Keep a record of what you’ve done so you’re ready when an opportunity appears.",
    category: "Resume Basics",
    video_youtube_id: null,
  },
  {
    slug: "honest-self-marketing",
    title: "Your LinkedIn Profile Is Your Professional Story",
    summary: "Help people understand what you know, what you’ve done, and how you add value.",
    category: "LinkedIn Basics",
    video_youtube_id: null,
  },
  {
    slug: "how-we-grade",
    title: "Prepare Stories, Not Perfect Answers",
    summary: "Use real examples to prepare for interview questions without memorizing a script.",
    category: "Interview Basics",
    video_youtube_id: null,
  },
];
