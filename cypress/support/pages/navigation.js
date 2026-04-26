class Navigation { 
  getStickyHeader() { 
    return cy.get('header'); 
  } 
  getAboutLink() { 
    return cy.get('a[href="#about"]').first(); 
  } 
  getProjectsLink() { 
    return cy.get('a[href="#projects"]').first(); 
  } 
  getContactLink() { 
    return cy.get('a[href="#contact"]').first(); 
  } 
} 
module.exports = new Navigation();