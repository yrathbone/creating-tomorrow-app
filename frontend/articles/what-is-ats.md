# What Is an ATS, Really?

*The software behind online job applications — without the mythology.*

*Estimated reading time: 6–8 minutes*

If you've applied for a job online, there's a good chance your application entered an Applicant Tracking System, or ATS.

You may have heard that an ATS is a robot that reads your resume, gives it a score, and decides whether a human will ever see it. Sometimes software does screen, rank, or match candidates. But that's only part of the story.

An ATS is better understood as a recruiting system that helps employers collect, organize, search, and manage applications. Different ATS products — and different employers using those products — can behave very differently.

**ATS ≠ one mysterious robot. ATS = software used to help manage recruiting.**

## First, Think of It as an Organized Filing System

Imagine a company receives hundreds of applications. Without software, recruiters would need to manually download resumes, keep track of applicants, record interview stages, and organize everything themselves. An ATS helps manage that process.

Depending on the system, an ATS may:

- Store resumes and applications
- Extract information from resumes into structured fields
- Help recruiters search or filter candidates
- Track applicants through interviews and hiring stages
- Support recruiting communication and scheduling
- Apply employer-defined screening criteria
- In some systems, calculate candidate-match scores or recommendations

Recruiting platforms including Workday and Lever document resume-parsing features that can extract information such as candidate names, contact details, employers, job titles, schools, and dates *(Source: Workday, Lever)*.

So the ATS isn't one single robot. It is an environment in which recruiting happens.

## What Does "Parsing" a Resume Mean?

A resume is designed for a person to look at. Computers often need something more structured. Resume parsing is the process of taking resume content and trying to identify pieces of information such as:

- Name
- Email
- Employer
- Job title
- Employment dates
- Education

Modern resume-parsing technology can use techniques such as optical character recognition, natural-language processing, and machine learning to identify these fields. But parsing is not perfect.

Workday's own documentation notes that parsing results can vary depending on resume format and word order *(Source: Workday)*. Greenhouse's support documentation similarly identifies non-standard formatting and embedded images as things that can prevent a resume from being successfully parsed, meaning a recruiter would need to enter that candidate's details by hand *(Source: Greenhouse)*.

It would be an overstatement to say "two-column resumes don't work." What's more accurate: different systems read documents differently. If maximum compatibility matters, simpler formatting reduces the number of things that can go wrong.

**More predictable to parse:**

- Clear headings
- Consistent dates
- Simple structure
- Important information written as text

**Less predictable to parse:**

- Complex text boxes
- Information embedded in graphics
- Highly unusual layouts
- Important content inside decorative elements

None of this means the second list is forbidden — only that it introduces more that can go wrong.

## What About Keywords?

Keywords matter because recruiters and recruiting systems can search and filter candidate information. If an employer is searching for experience involving Python, project management, commercial lending, or Spanish, clearly describing that real experience makes it easier for recruiters — or software — to identify it. Some systems now go beyond literal keyword searching and use candidate matching, recommendation systems, or semantic comparisons.

Here's the key distinction: the useful strategy is not to copy every word from a job posting. The useful strategy is to use the employer's language when it truthfully describes your experience.

**If you performed project management, say project management. If you didn't, don't add it because a scanner told you the phrase was missing.**

## Can You "Beat" an ATS With Keywords?

Researchers have demonstrated that automated ranking systems based on textual similarity can, in some cases, be manipulated through strategic text changes. Academic work by Anahita Samadi, Debapriya Banerjee, and Shirin Nilizadeh — ["Attacks against Ranking Algorithms with Text Embeddings: A Case Study on Recruitment Algorithms"](https://arxiv.org/abs/2108.05490), presented at the 2021 BlackboxNLP workshop — examined attacks against ranking algorithms that use text embeddings to compare resumes with job descriptions *(Source: Samadi, Banerjee & Nilizadeh, 2021)*.

This research does not prove that every commercial ATS works this way, and it does not mean candidates should keyword-stuff resumes. What it demonstrates is that automated ranking systems can have real limitations. Meanwhile, modern candidate-matching research increasingly leans on contextual language models and semantic relationships rather than only counting exact words — which makes crude keyword-stuffing less reliable, not more.

A better strategy is not keyword stuffing. It is truthful alignment.

## Can an ATS Automatically Reject Someone?

Sometimes. Employers may configure screening questions, filters, knockout criteria, assessments, automated matching, or candidate scoring. It isn't accurate to say ATS platforms never reject candidates automatically — and it's equally inaccurate to say every ATS automatically rejects anyone below some secret score. The amount of automation depends on the employer, the software being used, and how that employer configured the hiring process.

This isn't just a hypothetical concern. The U.S. government has taken a direct interest: official guidance from the Americans with Disabilities Act notes that algorithmic hiring tools — including resume-screening software — can screen out qualified people with disabilities, even unintentionally, and that employers remain responsible for those outcomes regardless of which vendor built the tool *(Source: [ADA.gov, "Algorithms, Artificial Intelligence, and Disability Discrimination in Hiring"](https://www.ada.gov/resources/ai-guidance/))*.

Technology can help organize hiring. It does not make hiring infallible.

## Can Software Understand Everything You've Done?

Modern systems are considerably more sophisticated than basic keyword matching, but understanding human career experience remains technically difficult. Here's the practical version: neither software nor a recruiter can understand experience that the resume doesn't explain clearly.

**Unclear:** Helped with reports.
**Clearer:** Prepared monthly financial reporting for senior management.

**Unclear:** Worked with customers.
**Clearer:** Resolved customer account issues and coordinated with operations teams to complete service requests.

The purpose isn't to make simple work sound grandiose. The purpose is to tell the reader what actually happened.

Clear writing helps technology understand your resume. More importantly, it helps people understand you.

## So What Does an ATS-Friendly Resume Look Like?

You do not need a secret formula.

- Clear section headings such as Experience, Education, and Skills
- Recognizable job titles and employment dates
- Straightforward formatting
- Important information written as text rather than embedded entirely inside graphics
- Consistent dates and employment structure
- Relevant skills described naturally within actual experience
- Job-description language when that language honestly matches your experience

If maximum parsing compatibility is the goal, a simple single-column resume remains a reasonable choice, since major ATS vendors' own documentation warns that complex layouts can affect parsing. That's exactly why Creating Tomorrow includes an ATS-focused single-column option — not because a visually distinctive resume is bad, but because clarity should come first.

## The Real Takeaway

Don't build your resume around defeating a machine. Build it around making your experience easy to understand.

- **Keep the formatting clear.**
- **Use recognizable professional language.**
- **Describe what you actually did.**
- **Use job-specific terminology when it is true.**
- **Write something a human will want to read.**

The best ATS strategy isn't trickery. It's clarity, relevance, and truth — and those happen to be good resume principles even when there isn't an ATS involved.

## Sources & Further Reading

**Official ATS / recruiting platform documentation**

- Workday — Resume Parsing (Recruiting admin documentation, doc.workday.com)
- Greenhouse — ["Unsuccessful resume parse"](https://support.greenhouse.io/hc/en-us/articles/200989175-Unsuccessful-resume-parse), Greenhouse Support Center
- Lever — resume parsing and candidate-profile documentation (referenced via Lever's published product documentation)

**Professional HR source**

- SHRM — general guidance describing applicant tracking systems and resume screening

**Government**

- U.S. Equal Employment Opportunity Commission — technical assistance on artificial intelligence and algorithmic decision-making tools in employment
- [ADA.gov — "Algorithms, Artificial Intelligence, and Disability Discrimination in Hiring"](https://www.ada.gov/resources/ai-guidance/)

**Academic research**

- Samadi, A., Banerjee, D., & Nilizadeh, S. (2021). ["Attacks against Ranking Algorithms with Text Embeddings: A Case Study on Recruitment Algorithms."](https://arxiv.org/abs/2108.05490) Proceedings of the Fourth BlackboxNLP Workshop on Analyzing and Interpreting Neural Networks for NLP.
