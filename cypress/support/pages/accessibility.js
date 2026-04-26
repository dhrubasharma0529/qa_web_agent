class Accessibility { 
  checkForMissingAriaLabels() { 
    return cy.get('button, input, textarea').each(($el) => { 
      cy.wrap($el).should('not.have.attr', 'aria-label'); 
    }); 
  } 
  checkKeyboardNavigation() { 
    return cy.get('input, button, textarea').focus(); 
  } 
} 
module.exports = new Accessibility();