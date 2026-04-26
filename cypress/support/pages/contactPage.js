class ContactPage { 
  visit() { 
    cy.visit('/contact'); 
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
} 
module.exports = new ContactPage();