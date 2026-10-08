// Shared article manifest: what the Learn page, the homepage guide tiles and the sitemap list.
// The four guides below each have a hand-built page inside article.html (the rich templates, keyed by
// slug). To add a SIMPLE article instead: (1) create frontend/articles/<slug>.md (plain headings,
// paragraphs, bold/italic, links and bullet lists; see markdown.js), and (2) add an entry here.
// A slug needs one or the other, never both. video_youtube_id is optional - set it to a YouTube
// video ID (the part after "v=" in a youtube.com URL) once a video exists, or leave null.
const ARTICLES = [
  {
    slug: "what-is-ats",
    title: "What Is an ATS, Really?",
    summary: "What you need to know about the software behind online job applications, without the myths.",
    category: "ATS Basics",
    video_youtube_id: null,
  },
  {
    slug: "resume-calling-card",
    title: "Your Resume Is Your Calling Card",
    summary: "Keep it ready before you need it.",
    category: "Resume Basics",
    video_youtube_id: null,
  },
  {
    slug: "honest-self-marketing",
    title: "Your LinkedIn Profile Is Your Professional Story",
    summary: "Present yourself honestly by showing what you know, what you've accomplished, and how you add value.",
    category: "LinkedIn Basics",
    video_youtube_id: null,
  },
  {
    slug: "how-we-grade",
    title: "Prepare Stories, Not Perfect Answers",
    summary: "How to prepare for an interview without memorizing a script.",
    category: "Interview Basics",
    video_youtube_id: null,
  },
];
