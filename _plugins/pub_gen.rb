module Jekyll
  class PubPage < Page
    def initialize(site, base, slug)
      @site = site
      @base = base
      @dir  = File.join('pub', slug)
      @name = 'index.html'

      self.process(@name)
      self.data    = { 'layout' => 'pub', 'pub_key' => slug }
      self.content = ''
    end
  end

  class PubGenerator < Generator
    safe true

    def generate(site)
      return unless site.data.key?('publications')

      site.data['publications'].each_key do |slug|
        page = PubPage.new(site, site.source, slug)
        page.render(site.layouts, site.site_payload)
        page.write(site.dest)
        site.pages << page
      end
    end
  end
end
