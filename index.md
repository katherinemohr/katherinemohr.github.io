---
layout: home
---

<link rel="stylesheet" href="/assets/css/homepage.css">

<div class="main-layout">
  <!-- Left Sidebar -->
  <aside class="sidebar">
    <div class="profile-section">
      <div class="profile-photo">
        <!-- Add your profile photo here -->
        <img src="/assets/images/pfp.jpg" alt="me in my favorite city! (cambridge, ma)" class="profile-image">
      </div>
      
      <h1 class="name">{{ site.title }}</h1>
      
      <div class="about-blurb">
        <p>{{ site.description }}</p>
      </div>
    </div>

    <div class="contact-links">
      <h3>Contact & Links</h3>
      <ul>
        <li><strong>Email:</strong> <a href="mailto:{{ site.email }}">{{ site.email }}</a></li>
        <li><strong>Twitter:</strong> <a href="https://twitter.com/{{ site.twitter_username }}" target="_blank">@{{ site.twitter_username }}</a></li>
        <li><strong>GitHub:</strong> <a href="https://github.com/{{ site.github_username }}" target="_blank">github.com/{{ site.github_username }}</a></li>
        <li><strong>CV:</strong> <a href="/assets/documents/cv.pdf" target="_blank">Download CV</a></li>
      </ul>
    </div>
  </aside>

  <!-- Main Content -->
  <main class="main-content">
    <h2>Recent Blog Posts</h2>

    <div class="recent-posts">
      {% assign recent_posts = site.posts | limit: 5 %}
      {% for post in recent_posts %}
        <div class="post-preview">
          <h3><a href="{{ post.url }}">{{ post.title }}</a></h3>
          <p class="post-date">{{ post.date | date: "%B %d, %Y" }}</p>
          <p class="post-excerpt">{{ post.excerpt | strip_html | truncatewords: 30 }}</p>
        </div>
      {% endfor %}
      
      <div class="view-all-posts">
        <a href="/jekyll/update/">View All Posts →</a>
      </div>
    </div>
  </main>
</div>

