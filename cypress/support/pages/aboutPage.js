class AboutPage { 
  visit() { 
    cy.visit('/about'); 
  } 
  getBiographySection() { 
    return cy.get('h2:contains("About Me")'); 
  } 
  getEducationSection() { 
    return cy.get('h3:contains("Education")'); 
  } 
  getExperienceSection() { 
    return cy.get('h3:contains("Experience")'); 
  } 
} 
module.exports = new AboutPage();