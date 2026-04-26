class HomePage { 
  visit() { 
    cy.visit('/'); 
  } 
  getHeroSection() { 
    return cy.get('h2:contains("Computer Engineer")'); 
  } 
  getPrimaryCTABtn() { 
    return cy.get('a[href="#projects"]').first(); 
  } 
  getAboutLink() { 
    return cy.get('a[href="#about"]'); 
  } 
  getProjectsLink() { 
    return cy.get('a[href="#projects"]'); 
  } 
  getContactLink() { 
    return cy.get('a[href="#contact"]'); 
  } 
  getContactForm() { 
    return cy.get('#contact-form'); 
  } 
  getNameInput() { 
    return cy.get('input[name="name"]'); 
  } 
  getEmailInput() { 
    return cy.get('input[name="email"]'); 
  } 
  getMessageTextarea() { 
    return cy.get('textarea[name="message"]'); 
  } 
  getSendMessageBtn() { 
    return cy.get('button[type="submit"]').first(); 
  } 
  getSkillsLink() { 
    return cy.get('a[href="#skills"]'); 
  } 
  getErrorMessage() { 
    return cy.get('[class*="error"]'); 
  } 
} 
module.exports = new HomePage();